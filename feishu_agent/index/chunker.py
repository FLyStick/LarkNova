"""把有序消息切分成与主题对齐的检索 chunk。

thread_id 是最强的分组信号；没有 thread 的消息按时间邻近分组，
并用消息数量/内容大小做上限，保证每次重建结果确定。
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
    """返回确定性的消息块列表，以及按消息 id 聚合的跳过分组原因。"""
    chunks: list[dict[str, Any]] = []
    skipped: dict[str, list[str]] = {}
    current: dict[str, Any] | None = None

    for row in rows:
        # 消息 id 是 chunk 内消息去重和溯源的最小单位，缺失时直接跳过。
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

        # thread 不一致或时间间隔过大时结束当前 chunk，保证话题尽量连续。
        if (
            current is not None
            and (
                thread_id != current["thread_id"]
                or _gap_exceeded(current.get("end_time_ms"), message_time, gap_seconds)
            )
        ):
            chunks.append(current)
            current = None

        # 首个消息或刚结束 chunk 时，用该消息的元数据初始化一个新的 chunk。
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

        # 达到消息数或字符数上限后立刻固化当前 chunk，避免单块过大。
        if (
            len(current["message_ids"]) >= max_messages
            or current["char_count"] >= max_chars
        ):
            chunks.append(current)
            current = None

    # 收尾时把未达到上限的最后一个 chunk 也固化。
    if current is not None:
        chunks.append(current)

    _materialize_chunks(chunks)
    return chunks, skipped


def _materialize_chunks(chunks: list[dict[str, Any]]) -> None:
    """对每个 chunk 计算序号、内容、哈希等派生字段，供索引仓库直接使用。"""
    for seq, chunk in enumerate(chunks, start=1):
        ids = chunk["message_ids"]
        content = "\n".join(chunk["lines"]).strip()
        start_time = chunk.get("start_time_ms")
        # 使用首条消息 id 作为 chunk 标识；无 thread 时退化为时间窗口键。
        chunk_id = str(ids[0]) if ids else ""
        topic_key = chunk["thread_id"] or f"window:{start_time or 0}"
        # 来源消息与正文均落库，后续可通过 content_hash 校验索引重建一致性。
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
    """返回消息被跳过的原因；可索引时返回 None。"""
    # 已删除、系统消息、空正文、归一化失败和低信号文本按序判断。
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
    """判断消息是否允许进入 chunk 与知识图谱构建。"""
    return (
        _skip_reason(row, include_system=include_system, skip_low_signal=skip_low_signal)
        is None
    )


def _chunk_line(row: Any, text: str) -> str:
    """拼接发送者前缀，让检索结果保留发言归属。"""
    sender = str(row.get("sender_name") or "").strip()
    if sender:
        return f"{sender}: {text}"
    return text


def _message_time_ms(row: Any) -> int | None:
    """优先读取毫秒时间戳，缺失时回退到可解析的 create_time。"""
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
    """时间间隔超过阈值时返回 True，用于按时间窗口切分非 thread 消息。"""
    if previous_ms is None or current_ms is None:
        return False
    return current_ms - previous_ms > gap_seconds * 1000


def _json_dumps(values: list[str]) -> str:
    """使用紧凑且确定性的 JSON 序列化消息 id 列表。"""
    import json

    return json.dumps(values, ensure_ascii=True, separators=(",", ":"))
