"""Persistent summary repository with rebuild/incremental/consistency checks."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from typing import Any

from feishu_agent.config import Settings
from feishu_agent.database.db import Database, iso_now
from feishu_agent.index.repository import IndexRepository
from feishu_agent.summary.factory import make_summarizer


class SummaryRepository:
    """Store one rolling structured summary per chat over indexed messages."""

    def __init__(self, db: Database, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or Settings()

    def rebuild(
        self,
        *,
        chat_ids: list[str] | None = None,
        allowed_chat_ids: set[str] | None = None,
        include_external: bool = False,
        mode: str = "rule",
    ) -> dict[str, Any]:
        selected = self._list_chats(
            chat_ids=chat_ids,
            allowed_chat_ids=allowed_chat_ids,
            include_external=include_external,
        )
        started = datetime.now().astimezone()
        totals = self._empty_totals()
        totals["chats_checked"] = len(selected)
        errors: list[dict[str, str]] = []
        checked_ids: list[str] = []
        summarized_ids: list[str] = []
        for chat in selected:
            chat_id = str(chat["chat_id"])
            checked_ids.append(chat_id)
            try:
                counts = self._summarize_chat(
                    chat_id,
                    str(chat.get("name") or ""),
                    mode,
                    replace=True,
                )
                self._add_counts(totals, counts)
                if counts["upserted"]:
                    summarized_ids.append(chat_id)
            except Exception as exc:
                errors.append(
                    {"chat_id": chat_id, "error": str(exc), "mode": mode}
                )
        totals["chats_failed"] = len(errors)
        scope = {
            "include_external": bool(include_external),
            "chat_ids": chat_ids or [],
            "mode": mode,
        }
        run_id = self._record_run(
            started=started,
            mode=mode,
            scope=scope,
            checked_ids=checked_ids,
            summarized_ids=summarized_ids,
            totals=totals,
            errors=errors,
        )
        return {
            "mode": mode,
            "operation": "rebuild",
            "run_id": run_id,
            "chats_checked": totals["chats_checked"],
            "chats_summarized": totals["chats_summarized"],
            "chats_failed": totals["chats_failed"],
            "messages_covered": totals["messages_covered"],
            "chunks_covered": totals["chunks_covered"],
            "summaries_upserted": totals["summaries_upserted"],
            "summaries_skipped": totals["summaries_skipped"],
            "errors": errors,
            "scope": scope,
        }

    def incremental(
        self,
        *,
        chat_ids: list[str] | None = None,
        allowed_chat_ids: set[str] | None = None,
        mode: str = "rule",
    ) -> dict[str, Any]:
        index_status = IndexRepository(self.db).status()
        if not index_status.get("indexed"):
            return {
                "mode": mode,
                "operation": "incremental",
                "built": False,
                "reason": "no_index",
                "chats_checked": 0,
                "chats_summarized": 0,
                "chats_failed": 0,
                "messages_covered": 0,
                "chunks_covered": 0,
                "summaries_upserted": 0,
                "summaries_skipped": 0,
                "errors": [],
            }
        last_index = index_status.get("last_run") or {}
        index_scope = last_index.get("scope") or {}
        include_external = bool(index_scope.get("allow_external"))
        selected = self._list_chats(
            chat_ids=chat_ids,
            allowed_chat_ids=allowed_chat_ids,
            include_external=include_external,
        )
        if not selected:
            return {
                "mode": mode,
                "operation": "incremental",
                "built": False,
                "reason": "no_chats",
                "chats_checked": 0,
                "chats_summarized": 0,
                "chats_failed": 0,
                "messages_covered": 0,
                "chunks_covered": 0,
                "summaries_upserted": 0,
                "summaries_skipped": 0,
                "errors": [],
            }

        started = datetime.now().astimezone()
        totals = self._empty_totals()
        totals["chats_checked"] = len(selected)
        errors: list[dict[str, str]] = []
        checked_ids: list[str] = []
        summarized_ids: list[str] = []
        reasons: list[str] = []
        for chat in selected:
            chat_id = str(chat["chat_id"])
            checked_ids.append(chat_id)
            try:
                decision = self._incremental_decision(
                    chat_id,
                    str(chat.get("name") or ""),
                    mode,
                )
                reasons.append(decision["reason"])
                if decision.get("counts"):
                    counts = decision["counts"]
                    self._add_counts(totals, counts)
                    if counts["upserted"]:
                        summarized_ids.append(chat_id)
                else:
                    totals["summaries_skipped"] += 1
            except Exception as exc:
                errors.append(
                    {"chat_id": chat_id, "error": str(exc), "mode": mode}
                )
        totals["chats_failed"] = len(errors)
        scope = {
            "include_external": include_external,
            "chat_ids": chat_ids or [],
            "mode": mode,
        }
        has_work = totals["summaries_upserted"] > 0 or bool(errors)
        run_id = None
        if has_work:
            run_id = self._record_run(
                started=started,
                mode=mode,
                scope=scope,
                checked_ids=checked_ids,
                summarized_ids=summarized_ids,
                totals=totals,
                errors=errors,
            )
        if totals["summaries_upserted"] > 0:
            reason = "summarized"
        elif "no_new_content" in reasons:
            reason = "no_new_content"
        elif "no_content" in reasons:
            reason = "no_content"
        else:
            reason = "no_changes"
        return {
            "mode": mode,
            "operation": "incremental",
            "built": totals["summaries_upserted"] > 0,
            "reason": reason,
            "run_id": run_id,
            "chats_checked": totals["chats_checked"],
            "chats_summarized": totals["chats_summarized"],
            "chats_failed": totals["chats_failed"],
            "messages_covered": totals["messages_covered"],
            "chunks_covered": totals["chunks_covered"],
            "summaries_upserted": totals["summaries_upserted"],
            "summaries_skipped": totals["summaries_skipped"],
            "errors": errors,
            "scope": scope,
        }

    def list_summaries(
        self,
        *,
        chat_ids: list[str] | None = None,
        period_start: str | None = None,
        period_end: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            where: list[str] = []
            params: list[Any] = []
            if chat_ids:
                where.append(
                    f"chat_id IN ({', '.join('?' * len(chat_ids))})"
                )
                params.extend(chat_ids)
            if period_start:
                where.append("period_start >= ?")
                params.append(period_start)
            if period_end:
                where.append("period_end <= ?")
                params.append(period_end)
            sql = "SELECT * FROM summaries"
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY period_end DESC, chat_id, id DESC LIMIT ?"
            params.append(max(1, min(int(limit), 200)))
            rows = conn.execute(sql, params).fetchall()
            return [self._decode_summary(row) for row in rows]
        finally:
            conn.close()

    def get(
        self,
        chat_id: str,
        period_start: str | None = None,
        period_end: str | None = None,
    ) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            if period_start and period_end:
                row = conn.execute(
                    """
                    SELECT * FROM summaries
                    WHERE chat_id = ? AND period_start = ? AND period_end = ?
                    ORDER BY id DESC LIMIT 1
                    """,
                    (chat_id, period_start, period_end),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT * FROM summaries
                    WHERE chat_id = ?
                    ORDER BY period_end DESC, id DESC LIMIT 1
                    """,
                    (chat_id,),
                ).fetchone()
            return self._decode_summary(row) if row else None
        finally:
            conn.close()

    def consistency(
        self,
        *,
        chat_ids: list[str] | None = None,
        allowed_chat_ids: set[str] | None = None,
        include_external: bool = False,
    ) -> dict[str, Any]:
        selected = self._list_chats(
            chat_ids=chat_ids,
            allowed_chat_ids=allowed_chat_ids,
            include_external=include_external,
        )
        conn = self._connect()
        try:
            per_chat: list[dict[str, Any]] = []
            for chat in selected:
                chat_id = str(chat["chat_id"])
                data = self._load_chat(conn, chat_id)
                existing = self._latest_summary_row(conn, chat_id)
                if not data["messages"]:
                    per_chat.append(
                        {
                            "chat_id": chat_id,
                            "chat_name": chat.get("name") or "",
                            "messages_covered": 0,
                            "chunks_covered": 0,
                            "has_summary": existing is not None,
                            "summary_messages": len(existing.get("source_message_ids") or [])
                            if existing
                            else 0,
                            "consistent": existing is None,
                            "missing": [],
                        }
                    )
                    continue
                current_ids = list(data["source_message_ids"])
                current_hash = data["source_message_hash"]
                old_ids = (
                    list(existing.get("source_message_ids") or [])
                    if existing
                    else []
                )
                old_hash = existing.get("source_message_hash") if existing else ""
                missing = [
                    item
                    for item in current_ids
                    if item not in set(old_ids)
                ]
                consistent = bool(
                    existing
                    and current_ids == old_ids
                    and current_hash == old_hash
                )
                per_chat.append(
                    {
                        "chat_id": chat_id,
                        "chat_name": chat.get("name") or "",
                        "messages_covered": len(current_ids),
                        "chunks_covered": len(data["chunks"]),
                        "has_summary": existing is not None,
                        "summary_messages": len(old_ids),
                        "consistent": consistent,
                        "missing": missing,
                    }
                )
            last = self._last_run_decoded()
            latest_change = conn.execute(
                "SELECT MAX(changed_at) AS ts FROM message_versions"
            ).fetchone()["ts"]
            fresh = bool(
                last
                and not last.get("errors")
                and (latest_change is None or last["finished_at"] >= latest_change)
            )
            return {
                "consistent": bool(selected)
                and all(item["consistent"] for item in per_chat)
                and fresh,
                "chats_checked": len(selected),
                "per_chat": per_chat,
                "freshness": {
                    "latest_message_changed_at": latest_change,
                    "fresh": fresh,
                },
            }
        finally:
            conn.close()

    def status(self) -> dict[str, Any]:
        conn = self._connect()
        try:
            counts = {
                "summaries": conn.execute(
                    "SELECT COUNT(*) FROM summaries"
                ).fetchone()[0],
                "summary_runs": conn.execute(
                    "SELECT COUNT(*) FROM summary_runs"
                ).fetchone()[0],
                "chats_summarized": conn.execute(
                    "SELECT COUNT(DISTINCT chat_id) FROM summaries"
                ).fetchone()[0],
                "messages_covered": conn.execute(
                    """
                    SELECT COALESCE(SUM(COALESCE(messages_covered, 0)), 0)
                    FROM summaries
                    """
                ).fetchone()[0],
                "chunks_covered": conn.execute(
                    """
                    SELECT COALESCE(SUM(COALESCE(chunks_covered, 0)), 0)
                    FROM summaries
                    """
                ).fetchone()[0],
                "token_estimate": conn.execute(
                    """
                    SELECT COALESCE(
                        SUM(
                            COALESCE(input_tokens, 0)
                            + COALESCE(output_tokens, 0)
                        ), 0
                    )
                    FROM summaries
                    """
                ).fetchone()[0],
            }
            last = self._last_run_decoded()
            latest_change = conn.execute(
                "SELECT MAX(changed_at) AS ts FROM message_versions"
            ).fetchone()["ts"]
            fresh = bool(
                last
                and not last.get("errors")
                and (latest_change is None or last["finished_at"] >= latest_change)
            )
            return {
                "built": last is not None,
                "runs_total": counts["summary_runs"],
                "last_run": last,
                "counts": counts,
                "latest_message_changed_at": latest_change,
                "fresh": fresh,
            }
        finally:
            conn.close()

    def _incremental_decision(
        self,
        chat_id: str,
        chat_name: str,
        mode: str,
    ) -> dict[str, Any]:
        conn = self._connect()
        try:
            data = self._load_chat(conn, chat_id)
        finally:
            conn.close()
        if not data["messages"]:
            return {"reason": "no_content", "counts": None}
        existing = self.get(chat_id)
        if existing is None:
            counts = self._summarize_chat(chat_id, chat_name, mode, replace=True)
            return {"reason": "no_summary", "counts": counts}
        current_ids = list(data["source_message_ids"])
        current_hash = data["source_message_hash"]
        old_ids = list(existing.get("source_message_ids") or [])
        old_hash = existing.get("source_message_hash") or ""
        if current_ids == old_ids and current_hash == old_hash:
            return {"reason": "no_changes", "counts": None}
        if current_hash != old_hash:
            counts = self._summarize_chat(chat_id, chat_name, mode, replace=True)
            return {"reason": "content_changed", "counts": counts}
        missing = [item for item in current_ids if item not in set(old_ids)]
        if len(missing) < self.settings.summary_min_new_messages:
            return {"reason": "no_new_content", "counts": None}
        counts = self._summarize_chat(chat_id, chat_name, mode, replace=True)
        return {"reason": "new_messages", "counts": counts}

    def _summarize_chat(
        self,
        chat_id: str,
        chat_name: str,
        mode: str,
        *,
        replace: bool,
    ) -> dict[str, int]:
        conn = self._connect()
        try:
            data = self._load_chat(conn, chat_id)
            if not data["messages"]:
                if replace:
                    conn.execute(
                        "DELETE FROM summaries WHERE chat_id = ?",
                        (chat_id,),
                    )
                    conn.commit()
                return {
                    "messages_covered": 0,
                    "chunks_covered": 0,
                    "upserted": 0,
                    "skipped": 1,
                }
            summarizer = make_summarizer(mode, self.settings)
            now = iso_now()
            result = summarizer.summarize_chat(
                chat_id,
                chat_name,
                data["chunks"],
                now,
            )
            structure = result.to_structure()
            summary_text = "\n".join(
                [
                    result.conclusion,
                    "依据：",
                    *result.evidence,
                    "待办：",
                    *result.todo,
                    "关键人：",
                    *result.key_people,
                    "关键日期：",
                    *result.key_dates,
                    "实体：",
                    *result.entities,
                ]
            ).strip()
            if replace:
                conn.execute(
                    "DELETE FROM summaries WHERE chat_id = ?",
                    (chat_id,),
                )
            conn.execute(
                """
                INSERT INTO summaries (
                    chat_id, period_start, period_end, summary, summary_json,
                    structure, conclusion, evidence, todo, key_people,
                    key_dates, entities, source_message_ids_json,
                    source_chunk_ids_json, source_message_hash, mode,
                    messages_covered, chunks_covered, input_tokens, output_tokens,
                    latency_ms, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, period_start, period_end) DO UPDATE SET
                    summary = excluded.summary,
                    summary_json = excluded.summary_json,
                    structure = excluded.structure,
                    conclusion = excluded.conclusion,
                    evidence = excluded.evidence,
                    todo = excluded.todo,
                    key_people = excluded.key_people,
                    key_dates = excluded.key_dates,
                    entities = excluded.entities,
                    source_message_ids_json = excluded.source_message_ids_json,
                    source_chunk_ids_json = excluded.source_chunk_ids_json,
                    source_message_hash = excluded.source_message_hash,
                    mode = excluded.mode,
                    messages_covered = excluded.messages_covered,
                    chunks_covered = excluded.chunks_covered,
                    input_tokens = excluded.input_tokens,
                    output_tokens = excluded.output_tokens,
                    latency_ms = excluded.latency_ms,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    chat_id,
                    data["period_start"],
                    data["period_end"],
                    summary_text,
                    json.dumps(structure, ensure_ascii=False),
                    json.dumps(structure, ensure_ascii=False),
                    result.conclusion,
                    "\n".join(result.evidence),
                    "\n".join(result.todo),
                    "\n".join(result.key_people),
                    "\n".join(result.key_dates),
                    "\n".join(result.entities),
                    json.dumps(data["source_message_ids"], ensure_ascii=False),
                    json.dumps(data["source_chunk_ids"], ensure_ascii=False),
                    data["source_message_hash"],
                    mode,
                    len(data["source_message_ids"]),
                    len(data["chunks"]),
                    int(result.input_tokens or 0),
                    int(result.output_tokens or 0),
                    int(result.latency_ms or 0),
                    "ok",
                    now,
                    now,
                ),
            )
            conn.commit()
            return {
                "messages_covered": len(data["source_message_ids"]),
                "chunks_covered": len(data["chunks"]),
                "upserted": 1,
                "skipped": 0,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _load_chat(
        self,
        conn: sqlite3.Connection,
        chat_id: str,
    ) -> dict[str, Any]:
        chunk_rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT id, chat_id, thread_id, topic_key, chunk_seq, content
                FROM chunks
                WHERE chat_id = ?
                ORDER BY chunk_seq
                """,
                (chat_id,),
            )
        ]
        message_rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT cm.chunk_id, cm.line_seq, m.message_id, m.chat_id,
                       m.sender_name, m.create_time, m.create_time_ms,
                       m.content_normalized, m.mentions_json, m.msg_type,
                       m.message_position
                FROM chunk_messages cm
                JOIN chunks c ON c.id = cm.chunk_id
                JOIN messages m ON m.message_id = cm.message_id
                WHERE c.chat_id = ? AND m.deleted = 0
                ORDER BY c.chunk_seq, cm.line_seq, m.message_position, m.message_id
                """,
                (chat_id,),
            )
        ]
        chunks: list[dict[str, Any]] = []
        by_chunk: dict[int, dict[str, Any]] = {}
        for chunk in chunk_rows:
            item = dict(chunk)
            item["messages"] = []
            by_chunk[int(item["id"])] = item
        for row in message_rows:
            chunk_id = int(row["chunk_id"])
            if chunk_id in by_chunk:
                by_chunk[chunk_id]["messages"].append(row)
        chunks = [by_chunk[key] for key in sorted(by_chunk)]

        messages: list[dict[str, Any]] = []
        seen: set[str] = set()
        for chunk in chunks:
            for row in chunk["messages"]:
                message_id = str(row["message_id"])
                if message_id in seen:
                    continue
                seen.add(message_id)
                messages.append(row)

        source_message_ids = [str(row["message_id"]) for row in messages]
        source_chunk_ids = [
            int(chunk["id"]) for chunk in chunks
        ]
        time_rows = [
            row
            for row in messages
            if row.get("create_time_ms") is not None
        ]
        if time_rows:
            earliest = min(time_rows, key=lambda row: row["create_time_ms"])
            latest = max(time_rows, key=lambda row: row["create_time_ms"])
            period_start = str(earliest.get("create_time") or iso_now())
            period_end = str(latest.get("create_time") or iso_now())
        else:
            raw_times = [
                str(row.get("create_time") or "")
                for row in messages
                if str(row.get("create_time") or "")
            ]
            period_start = min(raw_times) if raw_times else iso_now()
            period_end = max(raw_times) if raw_times else iso_now()
        return {
            "chunks": chunks,
            "messages": messages,
            "source_message_ids": source_message_ids,
            "source_chunk_ids": source_chunk_ids,
            "period_start": period_start,
            "period_end": period_end,
            "source_message_hash": self._source_hash(messages),
        }

    def _latest_summary_row(
        self,
        conn: sqlite3.Connection,
        chat_id: str,
    ) -> dict[str, Any] | None:
        row = conn.execute(
            """
            SELECT * FROM summaries
            WHERE chat_id = ?
            ORDER BY period_end DESC, id DESC LIMIT 1
            """,
            (chat_id,),
        ).fetchone()
        return self._decode_summary(row) if row else None

    @staticmethod
    def _source_hash(messages: list[dict[str, Any]]) -> str:
        items = sorted(
            (
                str(row["message_id"]),
                str(row.get("content_normalized") or ""),
            )
            for row in messages
        )
        payload = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _decode_summary(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        out = dict(row)
        for raw_key, target in (
            ("structure", "structure"),
            ("summary_json", "summary_json"),
            ("source_message_ids_json", "source_message_ids"),
            ("source_chunk_ids_json", "source_chunk_ids"),
        ):
            raw = out.get(raw_key)
            try:
                decoded = json.loads(raw or "null")
            except (TypeError, ValueError, json.JSONDecodeError):
                decoded = []
            out[target] = decoded
            if target != raw_key:
                out.pop(raw_key, None)
        return out

    def _list_chats(
        self,
        *,
        chat_ids: list[str] | None,
        allowed_chat_ids: set[str] | None,
        include_external: bool,
    ) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            where: list[str] = []
            params: list[Any] = []
            if not include_external:
                where.append("external = 0")
            if chat_ids:
                where.append(
                    f"chat_id IN ({', '.join('?' * len(chat_ids))})"
                )
                params.extend(chat_ids)
            sql = "SELECT chat_id, name, external FROM chats"
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY chat_id"
            rows = conn.execute(sql, params).fetchall()
            allowed = set(allowed_chat_ids) if allowed_chat_ids is not None else None
            return [
                dict(row)
                for row in rows
                if allowed is None or str(row["chat_id"]) in allowed
            ]
        finally:
            conn.close()

    def _record_run(
        self,
        *,
        started: datetime,
        mode: str,
        scope: dict[str, Any],
        checked_ids: list[str],
        summarized_ids: list[str],
        totals: dict[str, int],
        errors: list[dict[str, str]],
    ) -> int:
        finished = datetime.now().astimezone()
        duration_ms = int((finished - started).total_seconds() * 1000)
        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                INSERT INTO summary_runs (
                    started_at, finished_at, duration_ms, mode, scope,
                    chat_ids_json, chats_checked, chats_summarized,
                    messages_covered, chunks_covered, summaries_upserted,
                    summaries_skipped, errors_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    started.isoformat(timespec="seconds"),
                    finished.isoformat(timespec="seconds"),
                    duration_ms,
                    mode,
                    json.dumps(scope, ensure_ascii=False, sort_keys=True),
                    json.dumps(checked_ids, ensure_ascii=False),
                    int(totals["chats_checked"]),
                    int(totals.get("chats_summarized") or 0),
                    int(totals.get("messages_covered") or 0),
                    int(totals.get("chunks_covered") or 0),
                    int(totals.get("summaries_upserted") or 0),
                    int(totals.get("summaries_skipped") or 0),
                    json.dumps(errors, ensure_ascii=False),
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    def _last_run_decoded(self) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM summary_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return self._decode_run(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def _decode_run(row: sqlite3.Row) -> dict[str, Any]:
        run = dict(row)
        for key in ("errors_json",):
            try:
                run["errors"] = json.loads(run.pop(key) or "[]")
            except (TypeError, ValueError, json.JSONDecodeError):
                run["errors"] = []
        for key in ("scope", "chat_ids_json"):
            try:
                run[key] = json.loads(run[key] or "null")
            except (TypeError, ValueError, json.JSONDecodeError):
                run[key] = None
        return run

    @staticmethod
    def _empty_totals() -> dict[str, int]:
        return {
            "chats_checked": 0,
            "chats_summarized": 0,
            "chats_failed": 0,
            "messages_covered": 0,
            "chunks_covered": 0,
            "summaries_upserted": 0,
            "summaries_skipped": 0,
        }

    @staticmethod
    def _add_counts(
        totals: dict[str, int],
        counts: dict[str, int],
    ) -> None:
        totals["messages_covered"] += int(counts.get("messages_covered") or 0)
        totals["chunks_covered"] += int(counts.get("chunks_covered") or 0)
        totals["summaries_upserted"] += int(counts.get("upserted") or 0)
        totals["summaries_skipped"] += int(counts.get("skipped") or 0)
        if counts.get("upserted"):
            totals["chats_summarized"] += 1

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
