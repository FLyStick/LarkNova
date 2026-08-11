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
    """Return a normalized text snapshot and a stable content digest."""
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
    return html.unescape(_TAG_RE.sub("", text))


def _normalize_inline(text: str) -> str:
    text = _IMAGE_TAG_RE.sub(lambda m: f"[图片: {m.group(1).strip()}]", text)
    text = _IMAGE_MARKER_RE.sub(lambda m: f"[图片: {m.group(1).strip()}]", text)
    return text


def _dict_to_text(node: Any) -> str:
    parts: list[str] = []
    _collect_text(node, parts, set())
    return "\n".join(part for part in parts if part)


def _collect_text(node: Any, parts: list[str], seen: set[int]) -> None:
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
    if isinstance(raw, (dict, list)):
        try:
            return json.dumps(raw, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(raw)
    return "" if raw is None else str(raw)


def _clean_text(text: str) -> str:
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
