from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from feishu_agent.database.migrations import MIGRATIONS
from feishu_agent.normalize import normalize_message

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    chat_id TEXT PRIMARY KEY,
    name TEXT,
    description TEXT,
    chat_mode TEXT,
    chat_status TEXT,
    owner_id TEXT,
    external INTEGER DEFAULT 0,
    last_sync_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL,
    msg_type TEXT,
    content TEXT,
    content_raw TEXT,
    create_time TEXT,
    create_time_ms INTEGER,
    message_position INTEGER,
    sender_id TEXT,
    sender_name TEXT,
    sender_type TEXT,
    deleted INTEGER DEFAULT 0,
    updated INTEGER DEFAULT 0,
    mentions_json TEXT,
    thread_id TEXT,
    raw_json TEXT,
    first_seen_at TEXT,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_chat_time ON messages(chat_id, create_time);
CREATE INDEX IF NOT EXISTS idx_messages_type ON messages(msg_type);

CREATE TABLE IF NOT EXISTS sync_state (
    chat_id TEXT PRIMARY KEY,
    last_message_id TEXT,
    last_message_time TEXT,
    last_sync_at TEXT,
    status TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    period_start TEXT,
    period_end TEXT,
    summary TEXT,
    created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_summaries_chat ON summaries(chat_id);
"""


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def parse_create_time_ms(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value if value > 10**12 else value * 1000
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return int(datetime.strptime(text, fmt).timestamp() * 1000)
        except ValueError:
            continue
    try:
        numeric = int(text)
    except ValueError:
        return None
    return numeric if numeric > 10**12 else numeric * 1000


class Database:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self) -> None:
        conn = self._conn()
        try:
            conn.executescript(SCHEMA)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    description TEXT,
                    applied_at TEXT
                )
                """
            )
            applied = {
                int(row[0])
                for row in conn.execute("SELECT version FROM schema_migrations")
            }
            for migration in MIGRATIONS:
                if migration.version in applied:
                    continue
                migration.apply(conn)
                conn.execute(
                    """
                    INSERT INTO schema_migrations (version, description, applied_at)
                    VALUES (?, ?, ?)
                    """,
                    (migration.version, migration.description, iso_now()),
                )
            conn.commit()
        finally:
            conn.close()

    def upsert_chat(self, chat: dict[str, Any]) -> None:
        conn = self._conn()
        try:
            conn.execute(
                """
                INSERT INTO chats (
                    chat_id, name, description, chat_mode, chat_status,
                    owner_id, external, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    chat_mode = excluded.chat_mode,
                    chat_status = excluded.chat_status,
                    owner_id = excluded.owner_id,
                    external = excluded.external,
                    updated_at = excluded.updated_at
                """,
                (
                    chat.get("chat_id") or "",
                    chat.get("name"),
                    chat.get("description"),
                    chat.get("chat_mode"),
                    chat.get("chat_status"),
                    chat.get("owner_id"),
                    1 if chat.get("external") else 0,
                    iso_now(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def touch_chat_sync(self, chat_id: str) -> None:
        conn = self._conn()
        try:
            conn.execute(
                "UPDATE chats SET last_sync_at = ? WHERE chat_id = ?",
                (iso_now(), chat_id),
            )
            conn.commit()
        finally:
            conn.close()

    def list_chats(self) -> list[dict[str, Any]]:
        conn = self._conn()
        try:
            rows = conn.execute("SELECT * FROM chats ORDER BY updated_at DESC").fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def message_exists(self, message_id: str) -> bool:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT 1 FROM messages WHERE message_id = ?", (message_id,)
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def upsert_message(self, msg: dict[str, Any], seen_at: str | None = None) -> dict[str, Any]:
        normalized = normalize_message(msg)
        sender = msg.get("sender") or {}
        create_time = msg.get("create_time")
        content_raw = msg.get("content")
        content = normalized["content_normalized"]
        conn = self._conn()
        try:
            existing = conn.execute(
                """
                SELECT content_hash, deleted, updated, thread_id
                FROM messages
                WHERE message_id = ?
                """,
                (msg.get("message_id") or "",),
            ).fetchone()
            is_new = existing is None
            change_kind = (
                "created"
                if is_new
                else _message_change_kind(existing, msg, normalized)
            )
            changed = is_new or change_kind != "unchanged"
            version_seq: int | None = None
            if changed:
                version_seq = (
                    1
                    if is_new
                    else int(
                        conn.execute(
                            """
                            SELECT COALESCE(MAX(version_seq), 0) AS seq
                            FROM message_versions
                            WHERE message_id = ?
                            """,
                            (msg.get("message_id") or "",),
                        ).fetchone()["seq"]
                    )
                    + 1
                )
                conn.execute(
                    """
                    INSERT INTO message_versions (
                        message_id, version_seq, chat_id, msg_type, content_raw,
                        content_normalized, deleted, change_kind,
                        prev_content_hash, changed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        msg.get("message_id") or "",
                        version_seq,
                        msg.get("chat_id") or "",
                        msg.get("msg_type"),
                        _version_content_raw(content_raw),
                        normalized["content_normalized"],
                        1 if msg.get("deleted") else 0,
                        change_kind,
                        existing["content_hash"] if existing is not None else None,
                        iso_now(),
                    ),
                )
            conn.execute(
                """
                INSERT INTO messages (
                    message_id, chat_id, msg_type, content, content_raw,
                    content_normalized, content_hash, normalize_version,
                    normalize_error,
                    create_time, create_time_ms, message_position,
                    sender_id, sender_name, sender_type,
                    deleted, updated, mentions_json, thread_id,
                    raw_json, first_seen_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(message_id) DO UPDATE SET
                    chat_id = excluded.chat_id,
                    msg_type = excluded.msg_type,
                    content = excluded.content,
                    content_raw = excluded.content_raw,
                    content_normalized = excluded.content_normalized,
                    content_hash = excluded.content_hash,
                    normalize_version = excluded.normalize_version,
                    normalize_error = excluded.normalize_error,
                    create_time = excluded.create_time,
                    create_time_ms = excluded.create_time_ms,
                    message_position = excluded.message_position,
                    sender_id = excluded.sender_id,
                    sender_name = excluded.sender_name,
                    sender_type = excluded.sender_type,
                    deleted = excluded.deleted,
                    updated = excluded.updated,
                    mentions_json = excluded.mentions_json,
                    thread_id = excluded.thread_id,
                    raw_json = excluded.raw_json,
                    updated_at = excluded.updated_at
                """,
                (
                    msg.get("message_id") or "",
                    msg.get("chat_id") or "",
                    msg.get("msg_type"),
                    content,
                    json.dumps(content_raw, ensure_ascii=True) if content_raw is not None else None,
                    normalized["content_normalized"],
                    normalized["content_hash"],
                    normalized["normalize_version"],
                    normalized["normalize_error"],
                    create_time,
                    parse_create_time_ms(create_time),
                    _to_int(msg.get("message_position")),
                    sender.get("id"),
                    sender.get("name"),
                    sender.get("sender_type"),
                    1 if msg.get("deleted") else 0,
                    1 if msg.get("updated") else 0,
                    json.dumps(msg.get("mentions"), ensure_ascii=True) if msg.get("mentions") else None,
                    msg.get("thread_id"),
                    json.dumps(msg, ensure_ascii=True),
                    seen_at or iso_now(),
                    iso_now(),
                ),
            )
            conn.commit()
            return {
                "status": (
                    "created"
                    if is_new
                    else ("updated" if changed else "unchanged")
                ),
                "change_kind": change_kind,
                "version_seq": version_seq,
            }
        finally:
            conn.close()

    def get_sync_state(self, chat_id: str) -> dict[str, Any] | None:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM sync_state WHERE chat_id = ?", (chat_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def set_sync_state(
        self,
        chat_id: str,
        last_message_id: str | None = None,
        last_message_time: str | None = None,
        status: str = "ok",
        error: str | None = None,
        preserve_cursor: bool = False,
    ) -> None:
        conn = self._conn()
        try:
            if preserve_cursor:
                conn.execute(
                    """
                    INSERT INTO sync_state (
                        chat_id, last_message_id, last_message_time,
                        last_sync_at, status, error
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(chat_id) DO UPDATE SET
                        last_sync_at = excluded.last_sync_at,
                        status = excluded.status,
                        error = excluded.error
                    """,
                    (
                        chat_id,
                        _cursor_value(last_message_id),
                        _cursor_value(last_message_time),
                        iso_now(),
                        status,
                        error,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO sync_state (
                        chat_id, last_message_id, last_message_time,
                        last_sync_at, status, error
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(chat_id) DO UPDATE SET
                        last_message_id = excluded.last_message_id,
                        last_message_time = excluded.last_message_time,
                        last_sync_at = excluded.last_sync_at,
                        status = excluded.status,
                        error = excluded.error
                    """,
                    (chat_id, last_message_id, last_message_time, iso_now(), status, error),
                )
            conn.commit()
        finally:
            conn.close()

    def query_messages(
        self,
        chat_id: str | None = None,
        keyword: str | None = None,
        msg_type: str | None = None,
        sender_id: str | None = None,
        limit: int = 100,
        order: str = "asc",
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if chat_id:
            where.append("chat_id = ?")
            params.append(chat_id)
        if msg_type:
            where.append("msg_type = ?")
            params.append(msg_type)
        if sender_id:
            where.append("sender_id = ?")
            params.append(sender_id)
        if keyword:
            where.append("content LIKE ?")
            params.append(f"%{keyword}%")
        direction = "ASC" if order.lower() == "asc" else "DESC"
        sql = "SELECT * FROM messages"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY create_time {direction}, message_position {direction} LIMIT ?"
        params.append(max(1, min(int(limit), 500)))
        conn = self._conn()
        try:
            rows = conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()


    def count_messages(self, chat_id: str) -> int:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM messages WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
            return int(row["c"])
        finally:
            conn.close()

    def delete_chat(self, chat_id: str) -> dict[str, int]:
        conn = self._conn()
        try:
            conn.execute(
                """
                DELETE FROM message_versions
                WHERE message_id IN (SELECT message_id FROM messages WHERE chat_id = ?)
                """,
                (chat_id,),
            )
            messages_deleted = conn.execute(
                "DELETE FROM messages WHERE chat_id = ?", (chat_id,)
            ).rowcount
            conn.execute("DELETE FROM sync_state WHERE chat_id = ?", (chat_id,))
            conn.execute("DELETE FROM summaries WHERE chat_id = ?", (chat_id,))
            conn.execute("DELETE FROM chats WHERE chat_id = ?", (chat_id,))
            conn.commit()
            return {"chat_id": chat_id, "messages_deleted": messages_deleted}
        finally:
            conn.close()

    def rebuild_normalization(self) -> dict[str, Any]:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT message_id, raw_json, content FROM messages"
            ).fetchall()
            errors: list[dict[str, str]] = []
            for row in rows:
                message_id = row["message_id"]
                raw_json_text = row["raw_json"]
                msg: dict[str, Any] = {"message_id": message_id}
                if raw_json_text:
                    try:
                        parsed = json.loads(raw_json_text)
                        if isinstance(parsed, dict):
                            msg = parsed
                    except json.JSONDecodeError:
                        pass
                if "content" not in msg:
                    msg["content"] = row["content"]
                normalized = normalize_message(msg)
                conn.execute(
                    """
                    UPDATE messages
                    SET content = ?,
                        content_normalized = ?,
                        content_hash = ?,
                        normalize_version = ?,
                        normalize_error = ?
                    WHERE message_id = ?
                    """,
                    (
                        normalized["content_normalized"],
                        normalized["content_normalized"],
                        normalized["content_hash"],
                        normalized["normalize_version"],
                        normalized["normalize_error"],
                        message_id,
                    ),
                )
                if normalized["normalize_error"]:
                    errors.append(
                        {"message_id": message_id, "error": normalized["normalize_error"]}
                    )
            conn.commit()
            return {
                "messages_scanned": len(rows),
                "messages_rebuilt": len(rows),
                "normalize_errors": errors,
            }
        finally:
            conn.close()

    def record_sync_run(self, run: dict[str, Any]) -> None:
        conn = self._conn()
        try:
            conn.execute(
                """
                INSERT INTO sync_runs (
                    started_at, finished_at, duration_ms, identity, mode,
                    chats_scanned, chats_allowed, chats_skipped,
                    messages_new, messages_updated, messages_deleted,
                    messages_restored, errors_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.get("started_at"),
                    run.get("finished_at"),
                    _to_int(run.get("duration_ms")),
                    run.get("identity"),
                    run.get("mode"),
                    _to_int(run.get("chats_scanned")) or 0,
                    _to_int(run.get("chats_allowed")) or 0,
                    len(run.get("chats_skipped") or []),
                    _to_int(run.get("messages_new")) or 0,
                    _to_int(run.get("messages_updated")) or 0,
                    _to_int(run.get("messages_deleted")) or 0,
                    _to_int(run.get("messages_restored")) or 0,
                    json.dumps(run.get("errors") or [], ensure_ascii=False),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def recent_sync_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM sync_runs ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit), 200)),),
            ).fetchall()
            runs = [dict(row) for row in rows]
            for run in runs:
                try:
                    run["errors"] = json.loads(run.pop("errors_json") or "[]")
                except json.JSONDecodeError:
                    run["errors"] = []
            return runs
        finally:
            conn.close()

    def list_message_versions(
        self,
        message_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        where = ""
        params: list[Any] = []
        if message_id:
            where = " WHERE message_id = ?"
            params.append(message_id)
        params.append(max(1, min(int(limit), 1000)))
        conn = self._conn()
        try:
            rows = conn.execute(
                f"""
                SELECT * FROM message_versions{where}
                ORDER BY message_id, version_seq
                LIMIT ?
                """,
                params,
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def metrics(self, limit: int = 10) -> dict[str, Any]:
        conn = self._conn()
        try:
            stats = self.stats()
            sync_runs_total = conn.execute(
                "SELECT COUNT(*) AS c FROM sync_runs"
            ).fetchone()["c"]
            totals = conn.execute(
                """
                SELECT
                    COALESCE(SUM(messages_new), 0) AS messages_new,
                    COALESCE(SUM(messages_updated), 0) AS messages_updated,
                    COALESCE(SUM(messages_deleted), 0) AS messages_deleted,
                    COALESCE(SUM(messages_restored), 0) AS messages_restored,
                    COALESCE(SUM(duration_ms), 0) AS duration_ms
                FROM sync_runs
                """
            ).fetchone()
            last_run = conn.execute(
                "SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            sync_errors = conn.execute(
                """
                SELECT chat_id, status, error, last_sync_at
                FROM sync_state
                WHERE status = 'error'
                ORDER BY last_sync_at DESC
                """
            ).fetchall()
            return {
                "stats": stats,
                "sync_runs_total": sync_runs_total,
                "totals": {key: int(totals[key] or 0) for key in totals.keys()},
                "last_sync_run": dict(last_run) if last_run else None,
                "recent_sync_runs": self.recent_sync_runs(limit),
                "sync_errors": [dict(row) for row in sync_errors],
            }
        finally:
            conn.close()

    def stats(self) -> dict[str, int]:
        conn = self._conn()
        try:
            chats = conn.execute("SELECT COUNT(*) AS c FROM chats").fetchone()["c"]
            messages = conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"]
            external_chats = conn.execute(
                "SELECT COUNT(*) AS c FROM chats WHERE external = 1"
            ).fetchone()["c"]
            normalized = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM messages
                WHERE content_normalized IS NOT NULL AND content_normalized != ''
                """
            ).fetchone()["c"]
            normalize_errors = conn.execute(
                "SELECT COUNT(*) AS c FROM messages WHERE normalize_error IS NOT NULL"
            ).fetchone()["c"]
            versions = conn.execute(
                "SELECT COUNT(*) AS c FROM message_versions"
            ).fetchone()["c"]
            sync_runs = conn.execute(
                "SELECT COUNT(*) AS c FROM sync_runs"
            ).fetchone()["c"]
            return {
                "chats": chats,
                "messages": messages,
                "external_chats": external_chats,
                "normalized": normalized,
                "normalize_errors": normalize_errors,
                "versions": versions,
                "sync_runs": sync_runs,
            }
        finally:
            conn.close()


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _cursor_value(value: Any) -> Any:
    return None if value is None else str(value)


def _message_change_kind(
    existing: sqlite3.Row,
    msg: dict[str, Any],
    normalized: dict[str, Any],
) -> str:
    was_deleted = bool(existing["deleted"])
    now_deleted = bool(msg.get("deleted"))
    if was_deleted != now_deleted:
        return "restored" if not now_deleted else "recalled"
    if existing["content_hash"] != normalized["content_hash"]:
        return "content_updated"
    if bool(existing["updated"]) != bool(msg.get("updated")):
        return "metadata_updated"
    return "unchanged"


def _version_content_raw(content: Any) -> str | None:
    if content is None:
        return None
    if isinstance(content, (dict, list)):
        return json.dumps(content, ensure_ascii=False, default=str)
    return str(content)
