"""Turn ordered messages into topic-aligned retrieval chunks.

Thread id is the strongest grouping signal. Messages without a thread are
grouped by time proximity and capped by message count/content size so one
reconstruction run stays deterministic.
"""

from __future__ import annotations

import hashlib
from typing import Any

from feishu_agent.database.db import parse_create_time_ms

DEFAULT_GAP_SECONDS = 30 * 60
DEFAULT_MAX_MESSAGES = 30
DEFAULT_MAX_CHARS = 4000

LOW_SIGNAL_TEXTS = {
    "The message has exceeded the retention period and has been deleted.",
}

LOW_SIGNAL_TEXTS_FROZEN = frozenset(LOW_SIGNAL_TEXTS)


def build_chunks(
    rows: list[Any],
    *,
    gap_seconds: int = DEFAULT_GAP_SECONDS,
    max_messages: int = DEFAULT_MAX_MESSAGES,
    max_chars: int = DEFAULT_MAX_CHARS,
    include_system: bool = False,
    skip_low_signal: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """Return deterministic chunks and skip reasons keyed by message id."""
    chunks: list[dict[str, Any]] = []
    skipped: dict[str, list[str]] = {}
    current: dict[str, Any] | None = None

    for row in rows:
        message_id = str(row.get("message_id") or "")
        if not message_id:
            skipped.setdefault(message_id, []).append("missing_message_id")
            continue
        reason = _skip_reason(row, include_system=include_system, skip_low_signal=skip_low_signal)
        if reason:
            skipped.setdefault(message_id, []).append(reason)
            continue

        text = str(row.get("content_normalized") or "").strip()
        message_time = _message_time_ms(row)
        thread_id = str(row.get("thread_id") or "")
        line = _chunk_line(row, text)

        if (
            current is not None
            and (
                thread_id != current["thread_id"]
                or _gap_exceeded(current.get("end_time_ms"), message_time, gap_seconds)
            )
        ):
            chunks.append(current)
            current = None

        if current is None:
            current = {
                "chat_id": str(row.get("chat_id") or ""),
                "thread_id": thread_id,
                "message_ids": [],
                "lines": [],
                "char_count": 0,
                "start_time_ms": message_time,
                "end_time_ms": message_time,
            }

        current["message_ids"].append(message_id)
        current["lines"].append(line)
        current["char_count"] += len(line)
        current["end_time_ms"] = message_time

        if (
            len(current["message_ids"]) >= max_messages
            or current["char_count"] >= max_chars
        ):
            chunks.append(current)
            current = None

    if current is not None:
        chunks.append(current)

    _materialize_chunks(chunks)
    return chunks, skipped


def _materialize_chunks(chunks: list[dict[str, Any]]) -> None:
    for seq, chunk in enumerate(chunks, start=1):
        ids = chunk["message_ids"]
        content = "\n".join(chunk["lines"]).strip()
        start_time = chunk.get("start_time_ms")
        chunk_id = str(ids[0]) if ids else ""
        topic_key = chunk["thread_id"] or f"window:{start_time or 0}"
        chunk.update(
            {
                "chunk_seq": seq,
                "topic_key": topic_key,
                "message_id_start": chunk_id,
                "message_id_end": str(ids[-1]) if ids else chunk_id,
                "message_count": len(ids),
                "message_ids_json": _json_dumps(ids),
                "content": content,
                "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            }
        )
        chunk.pop("lines", None)
        chunk.pop("char_count", None)


def _skip_reason(row: Any, *, include_system: bool, skip_low_signal: bool) -> str | None:
    if row.get("deleted"):
        return "deleted"
    if not include_system and row.get("msg_type") == "system":
        return "system"
    text = str(row.get("content_normalized") or "").strip()
    if not text:
        return "empty_content"
    if row.get("normalize_error"):
        return "normalize_error"
    if skip_low_signal and text in LOW_SIGNAL_TEXTS_FROZEN:
        return "low_signal"
    return None


def message_indexable(
    row: Any,
    *,
    include_system: bool = False,
    skip_low_signal: bool = True,
) -> bool:
    """Return True when a message row is eligible for chunking and graphing."""
    return (
        _skip_reason(row, include_system=include_system, skip_low_signal=skip_low_signal)
        is None
    )


def _chunk_line(row: Any, text: str) -> str:
    sender = str(row.get("sender_name") or "").strip()
    if sender:
        return f"{sender}: {text}"
    return text


def _message_time_ms(row: Any) -> int | None:
    value = row.get("create_time_ms")
    if value is not None:
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    return parse_create_time_ms(row.get("create_time"))


def _gap_exceeded(
    previous_ms: int | None,
    current_ms: int | None,
    gap_seconds: int,
) -> bool:
    if previous_ms is None or current_ms is None:
        return False
    return current_ms - previous_ms > gap_seconds * 1000


def _json_dumps(values: list[str]) -> str:
    import json

    return json.dumps(values, ensure_ascii=True, separators=(",", ":"))
