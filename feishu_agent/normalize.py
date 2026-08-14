"""消息标准化：把飞书多类型消息归一成可检索文本，并计算内容摘要指纹。"""

from __future__ import annotations

import hashlib
import html
import json
import re
from typing import Any

NORMALIZE_VERSION = 1

_IMAGE_TAG_RE = re.compile(r"!\[[^\]]*\]\(([^)]*)\)")
_IMAGE_MARKER_RE = re.compile(r"\[Image:\s*([^\]]+)\]")
_TAG_RE = re.compile(r"<[^>]+>")

_TEXT_KEYS = (
    "text",
    "content",
    "title",
    "subtitle",
    "label",
    "name",
    "value",
    "href",
    "url",
    "description",
)
_CHILD_KEYS = ("elements", "children", "content", "markdown", "mrkdwn", "plain_text", "lines")


def normalize_message(msg: dict[str, Any]) -> dict[str, Any]:
    """标准化单条消息，返回清洗后的文本、内容哈希和归一化版本信息。"""
    msg_type = str(msg.get("msg_type") or "text")
    raw_content = msg.get("content")
    error = None
    try:
        text = _normalize_content(msg_type, raw_content)
    except Exception as exc:  # normalization must never break ingestion
        text = _fallback_text(raw_content)
        error = str(exc)
    return {
        "content_normalized": _clean_text(text),
        "content_hash": message_digest(msg),
        "normalize_version": NORMALIZE_VERSION,
        "normalize_error": error,
    }


def message_digest(msg: dict[str, Any]) -> str:
    """基于消息关键字段生成稳定 SHA-256，用于幂等重建与变更检测。"""
    payload = {
        "msg_type": msg.get("msg_type"),
        "content": msg.get("content"),
        "deleted": bool(msg.get("deleted")),
        "updated": bool(msg.get("updated")),
        "thread_id": msg.get("thread_id"),
        "chat_id": msg.get("chat_id"),
        "message_position": msg.get("message_position"),
        "create_time": msg.get("create_time"),
    }
    dumped = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def _normalize_content(msg_type: str, raw: Any) -> str:
    """按消息类型递归提取纯文本，交互卡片优先解析 JSON 结构。"""
    if raw is None:
        return ""
    if isinstance(raw, dict):
        return _dict_to_text(raw)
    if not isinstance(raw, str):
        return str(raw)
    text = raw.strip()
    if not text:
        return ""
    if msg_type == "interactive" and text.startswith("{"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, (dict, list)):
            return _dict_to_text(parsed)
    if text.startswith("<") or msg_type in {"interactive", "merge_forward", "share_chat"}:
        text = _strip_markup(text)
    return _normalize_inline(text)


def _strip_markup(text: str) -> str:
    """去掉 HTML 标签并还原常见实体字符。"""
    return html.unescape(_TAG_RE.sub("", text))


def _normalize_inline(text: str) -> str:
    """把 Markdown 图片与 [Image: ...] 标记统一替换为 [图片: 来源]。"""
    text = _IMAGE_TAG_RE.sub(lambda m: f"[图片: {m.group(1).strip()}]", text)
    text = _IMAGE_MARKER_RE.sub(lambda m: f"[图片: {m.group(1).strip()}]", text)
    return text


def _dict_to_text(node: Any) -> str:
    """递归把富文本结构转换成按行拼接的纯文本。"""
    parts: list[str] = []
    _collect_text(node, parts, set())
    return "\n".join(part for part in parts if part)


def _collect_text(node: Any, parts: list[str], seen: set[int]) -> None:
    """深度遍历消息结构，抽取文本字段并用 seen 防止循环引用。"""
    if isinstance(node, str):
        text = node.strip()
        if text:
            parts.append(text)
        return
    if isinstance(node, list):
        for item in node:
            _collect_text(item, parts, seen)
        return
    if not isinstance(node, dict):
        text = str(node).strip()
        if text:
            parts.append(text)
        return
    marker = id(node)
    if marker in seen:
        return
    seen.add(marker)
    tag = str(node.get("tag") or "").lower()
    if tag in {"img", "image", "media"}:
        parts.append("[图片]")
    for key in _TEXT_KEYS:
        if key in node and isinstance(node[key], str) and node[key].strip():
            parts.append(node[key].strip())
    for key in _CHILD_KEYS:
        if key in node:
            _collect_text(node[key], parts, seen)


def _fallback_text(raw: Any) -> str:
    """归一化失败时兜底：结构直接序列化，其余转字符串。"""
    if isinstance(raw, (dict, list)):
        try:
            return json.dumps(raw, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(raw)
    return "" if raw is None else str(raw)


def _clean_text(text: str) -> str:
    """压缩连续空行并去除首尾空白，保持全文格式稳定。"""
    lines: list[str] = []
    blank = False
    for line in re.split(r"\r?\n", text):
        cleaned = line.rstrip()
        if not cleaned.strip():
            if blank:
                continue
            blank = True
            lines.append("")
        else:
            blank = False
            lines.append(cleaned)
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines).strip()
