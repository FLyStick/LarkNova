from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from feishu_agent.normalize import normalize_message


@dataclass(frozen=True)
class Migration:
    version: int
    description: str
    apply: Callable[[sqlite3.Connection], None]


def _ensure_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    ddl: str,
) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _apply_v2(conn: sqlite3.Connection) -> None:
    """M1: normalized text hash, message version audit and sync metrics."""
    _ensure_column(conn, "messages", "content_normalized", "TEXT")
    _ensure_column(conn, "messages", "content_hash", "TEXT")
    _ensure_column(conn, "messages", "normalize_version", "INTEGER DEFAULT 0")
    _ensure_column(conn, "messages", "normalize_error", "TEXT")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS message_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT NOT NULL,
            version_seq INTEGER NOT NULL,
            chat_id TEXT,
            msg_type TEXT,
            content_raw TEXT,
            content_normalized TEXT,
            deleted INTEGER DEFAULT 0,
            change_kind TEXT,
            prev_content_hash TEXT,
            changed_at TEXT,
            UNIQUE(message_id, version_seq)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_message_versions_message
        ON message_versions(message_id, version_seq)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sync_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT,
            finished_at TEXT,
            duration_ms INTEGER,
            identity TEXT,
            mode TEXT,
            chats_scanned INTEGER DEFAULT 0,
            chats_allowed INTEGER DEFAULT 0,
            chats_skipped INTEGER DEFAULT 0,
            messages_new INTEGER DEFAULT 0,
            messages_updated INTEGER DEFAULT 0,
            messages_deleted INTEGER DEFAULT 0,
            messages_restored INTEGER DEFAULT 0,
            errors_json TEXT
        )
        """
    )
    _backfill_normalized(conn)


def _apply_v3(conn: sqlite3.Connection) -> None:
    """Repair databases that recorded v2 before content_normalized existed."""
    _ensure_column(conn, "messages", "content_normalized", "TEXT")
    _backfill_normalized(conn)


def _backfill_normalized(conn: sqlite3.Connection) -> None:
    """Fill normalized columns and an initial version row for legacy messages."""
    rows = conn.execute(
        """
        SELECT message_id, chat_id, msg_type, raw_json, content, deleted, updated
        FROM messages
        """
    ).fetchall()
    changed_at = datetime.now().astimezone().isoformat(timespec="seconds")
    for message_id, chat_id, msg_type, raw_json_text, content, deleted, updated in rows:
        msg: dict = {
            "message_id": message_id,
            "chat_id": chat_id,
            "msg_type": msg_type,
            "deleted": bool(deleted),
            "updated": bool(updated),
        }
        if raw_json_text:
            try:
                parsed = json.loads(raw_json_text)
                if isinstance(parsed, dict):
                    msg = parsed
            except json.JSONDecodeError:
                pass
        if "content" not in msg:
            msg["content"] = content
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
        raw_version = content
        if isinstance(raw_version, (dict, list)):
            raw_version = json.dumps(raw_version, ensure_ascii=False, default=str)
        elif raw_version is not None:
            raw_version = str(raw_version)
        conn.execute(
            """
            INSERT OR IGNORE INTO message_versions (
                message_id, version_seq, chat_id, msg_type, content_raw,
                content_normalized, deleted, change_kind, prev_content_hash,
                changed_at
            ) VALUES (?, 1, ?, ?, ?, ?, ?, 'initial', NULL, ?)
            """,
            (
                message_id,
                chat_id,
                msg_type,
                raw_version,
                normalized["content_normalized"],
                1 if bool(deleted) else 0,
                changed_at,
            ),
        )


MIGRATIONS = [
    Migration(
        2,
        "M1 data pipeline: content hash, message versions, sync metrics",
        _apply_v2,
    ),
    Migration(
        3,
        "M1 repair: ensure content_normalized column and backfill it",
        _apply_v3,
    ),
]
