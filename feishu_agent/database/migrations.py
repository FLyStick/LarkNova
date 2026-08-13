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


def _apply_v4(conn: sqlite3.Connection) -> None:
    """M2: derived topic chunks, FTS5 full-text index, sparse vectors, graph."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            thread_id TEXT,
            topic_key TEXT NOT NULL,
            chunk_seq INTEGER NOT NULL,
            message_id_start TEXT,
            message_id_end TEXT,
            message_count INTEGER NOT NULL,
            message_ids_json TEXT NOT NULL,
            content TEXT NOT NULL,
            search_text TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            start_time_ms INTEGER,
            end_time_ms INTEGER,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_chunks_chat
        ON chunks(chat_id, chunk_seq);
        CREATE INDEX IF NOT EXISTS idx_chunks_topic
        ON chunks(topic_key);

        CREATE TABLE IF NOT EXISTS chunk_messages (
            chunk_id INTEGER NOT NULL,
            message_id TEXT NOT NULL,
            line_seq INTEGER NOT NULL,
            PRIMARY KEY (chunk_id, message_id)
        );
        CREATE INDEX IF NOT EXISTS idx_chunk_messages_message
        ON chunk_messages(message_id);

        CREATE TABLE IF NOT EXISTS chunk_vectors (
            chunk_id INTEGER PRIMARY KEY,
            total_terms INTEGER NOT NULL DEFAULT 0,
            term_freqs_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS entities (
            entity_id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            value TEXT NOT NULL,
            canonical TEXT NOT NULL,
            occurrence INTEGER NOT NULL DEFAULT 0,
            first_seen_at_ms INTEGER,
            last_seen_at_ms INTEGER,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);
        CREATE INDEX IF NOT EXISTS idx_entities_value ON entities(value);

        CREATE TABLE IF NOT EXISTS entity_mentions (
            entity_id TEXT NOT NULL,
            message_id TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            occurrence INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (entity_id, message_id)
        );
        CREATE INDEX IF NOT EXISTS idx_mentions_chat ON entity_mentions(chat_id);
        CREATE INDEX IF NOT EXISTS idx_mentions_message ON entity_mentions(message_id);

        CREATE TABLE IF NOT EXISTS edges (
            edge_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_entity_id TEXT NOT NULL,
            target_entity_id TEXT NOT NULL,
            edge_type TEXT NOT NULL,
            chat_id TEXT,
            message_id TEXT,
            weight REAL NOT NULL DEFAULT 1,
            evidence_text TEXT,
            created_at TEXT,
            updated_at TEXT,
            UNIQUE(source_entity_id, target_entity_id, edge_type, chat_id, message_id)
        );
        CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_entity_id);
        CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_entity_id);
        CREATE INDEX IF NOT EXISTS idx_edges_chat ON edges(chat_id);
        CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(edge_type);

        CREATE TABLE IF NOT EXISTS index_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT,
            finished_at TEXT,
            duration_ms INTEGER,
            mode TEXT,
            scope TEXT,
            chat_ids_json TEXT,
            rebuild_id TEXT,
            version_cursor INTEGER,
            chats_indexed INTEGER DEFAULT 0,
            chats_failed INTEGER DEFAULT 0,
            messages_scanned INTEGER DEFAULT 0,
            messages_indexed INTEGER DEFAULT 0,
            messages_skipped INTEGER DEFAULT 0,
            chunks_created INTEGER DEFAULT 0,
            vectors_created INTEGER DEFAULT 0,
            entities_created INTEGER DEFAULT 0,
            edges_created INTEGER DEFAULT 0,
            errors_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_index_runs_finished ON index_runs(finished_at);
        CREATE INDEX IF NOT EXISTS idx_index_runs_mode ON index_runs(mode);
        CREATE INDEX IF NOT EXISTS idx_message_versions_changed_at
        ON message_versions(changed_at);

        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            search_text,
            content='chunks',
            content_rowid='id'
        );

        CREATE TRIGGER IF NOT EXISTS chunks_fts_ai AFTER INSERT ON chunks BEGIN
            INSERT INTO chunks_fts(rowid, search_text)
            VALUES (new.id, new.search_text);
        END;

        CREATE TRIGGER IF NOT EXISTS chunks_fts_ad AFTER DELETE ON chunks BEGIN
            INSERT INTO chunks_fts(chunks_fts, rowid, search_text)
            VALUES ('delete', old.id, old.search_text);
        END;

        CREATE TRIGGER IF NOT EXISTS chunks_fts_au AFTER UPDATE ON chunks BEGIN
            INSERT INTO chunks_fts(chunks_fts, rowid, search_text)
            VALUES ('delete', old.id, old.search_text);
            INSERT INTO chunks_fts(rowid, search_text)
            VALUES (new.id, new.search_text);
        END;
        """
    )


def _apply_v5(conn: sqlite3.Connection) -> None:
    """M3: replace the placeholder summaries table and add run audit records."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(summaries)")}
    required = {
        "summary_json",
        "structure",
        "source_message_ids_json",
        "source_chunk_ids_json",
        "source_message_hash",
        "mode",
        "messages_covered",
        "chunks_covered",
        "updated_at",
    }
    if not required.issubset(columns):
        conn.executescript(
            """
            DROP TABLE IF EXISTS summaries_new;

            CREATE TABLE summaries_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                period_start TEXT,
                period_end TEXT,
                summary TEXT,
                summary_json TEXT,
                structure TEXT,
                conclusion TEXT,
                evidence TEXT,
                todo TEXT,
                key_people TEXT,
                key_dates TEXT,
                entities TEXT,
                source_message_ids_json TEXT,
                source_chunk_ids_json TEXT,
                source_message_hash TEXT,
                mode TEXT,
                messages_covered INTEGER DEFAULT 0,
                chunks_covered INTEGER DEFAULT 0,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                latency_ms INTEGER DEFAULT 0,
                status TEXT DEFAULT 'ok',
                created_at TEXT,
                updated_at TEXT,
                UNIQUE(chat_id, period_start, period_end)
            );
            """
        )
        conn.execute(
            """
            INSERT INTO summaries_new (
                id, chat_id, period_start, period_end, summary, created_at
            )
            SELECT id, chat_id, period_start, period_end, summary, created_at
            FROM summaries
            """
        )
        conn.execute("DROP TABLE summaries")
        conn.execute("ALTER TABLE summaries_new RENAME TO summaries")

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_summaries_chat ON summaries(chat_id)"
    )
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS summary_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT,
            finished_at TEXT,
            duration_ms INTEGER,
            mode TEXT,
            scope TEXT,
            chat_ids_json TEXT,
            chats_checked INTEGER DEFAULT 0,
            chats_summarized INTEGER DEFAULT 0,
            messages_covered INTEGER DEFAULT 0,
            chunks_covered INTEGER DEFAULT 0,
            summaries_upserted INTEGER DEFAULT 0,
            summaries_skipped INTEGER DEFAULT 0,
            errors_json TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_summary_runs_finished
        ON summary_runs(finished_at);
        CREATE INDEX IF NOT EXISTS idx_summary_runs_mode
        ON summary_runs(mode);
        """
    )


def _apply_v6(conn: sqlite3.Connection) -> None:
    """M4: agent runs and replayable intermediate trace steps."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS agent_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trace_id TEXT NOT NULL UNIQUE,
            question TEXT NOT NULL,
            mode TEXT NOT NULL,
            status TEXT NOT NULL,
            answer TEXT,
            refusal_reason TEXT,
            degraded INTEGER NOT NULL DEFAULT 0,
            chat_ids_json TEXT NOT NULL DEFAULT '[]',
            citations_json TEXT NOT NULL DEFAULT '[]',
            tokens INTEGER NOT NULL DEFAULT 0,
            latency_ms INTEGER NOT NULL DEFAULT 0,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_agent_runs_finished
        ON agent_runs(finished_at);
        CREATE INDEX IF NOT EXISTS idx_agent_runs_status
        ON agent_runs(status);

        CREATE TABLE IF NOT EXISTS agent_traces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            trace_id TEXT NOT NULL,
            step_seq INTEGER NOT NULL,
            step_kind TEXT NOT NULL,
            tool TEXT,
            status TEXT NOT NULL,
            input_json TEXT,
            output_json TEXT,
            error TEXT,
            latency_ms INTEGER NOT NULL DEFAULT 0,
            started_at TEXT NOT NULL,
            UNIQUE(run_id, step_seq)
        );
        CREATE INDEX IF NOT EXISTS idx_agent_traces_run
        ON agent_traces(run_id);
        CREATE INDEX IF NOT EXISTS idx_agent_traces_trace
        ON agent_traces(trace_id);
        """
    )


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
    Migration(
        4,
        "M2 topic index: chunks, FTS5 BM25, sparse TF-IDF, knowledge graph",
        _apply_v4,
    ),
    Migration(
        5,
        "M3 AI summary: structured summary tables",
        _apply_v5,
    ),
    Migration(
        6,
        "M4 agent harness: agent runs and trace steps",
        _apply_v6,
    ),
]
