from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

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

    def upsert_message(self, msg: dict[str, Any], seen_at: str | None = None) -> None:
        sender = msg.get("sender") or {}
        create_time = msg.get("create_time")
        content_raw = msg.get("content")
        content = content_raw
        if isinstance(content_raw, dict):
            content = json.dumps(content_raw, ensure_ascii=True)
        elif isinstance(content_raw, str):
            try:
                parsed = json.loads(content_raw)
                if isinstance(parsed, dict):
                    content = parsed.get("text") or parsed.get("title") or content_raw
                elif isinstance(parsed, list):
                    content = content_raw
            except json.JSONDecodeError:
                pass
        conn = self._conn()
        try:
            conn.execute(
                """
                INSERT INTO messages (
                    message_id, chat_id, msg_type, content, content_raw,
                    create_time, create_time_ms, message_position,
                    sender_id, sender_name, sender_type,
                    deleted, updated, mentions_json, thread_id,
                    raw_json, first_seen_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(message_id) DO UPDATE SET
                    chat_id = excluded.chat_id,
                    msg_type = excluded.msg_type,
                    content = excluded.content,
                    content_raw = excluded.content_raw,
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
    ) -> None:
        conn = self._conn()
        try:
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

    def stats(self) -> dict[str, int]:
        conn = self._conn()
        try:
            chats = conn.execute("SELECT COUNT(*) AS c FROM chats").fetchone()["c"]
            messages = conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"]
            return {"chats": chats, "messages": messages}
        finally:
            conn.close()


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
