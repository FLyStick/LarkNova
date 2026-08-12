"""Rule-based entity and relation extraction for the local knowledge graph."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_DEPARTMENT_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?:人事|财务|风控|招采|采购|技术|产品|运营|法务|行政|市场|研发|设计|数据|质检)"
    r"(?:部|组|中心|团队|委员会)?"
)
_DATE_RE = re.compile(
    r"(?:20\d{2}[-/年]\d{1,2}(?:[-/月]\d{1,2}日?)?|\d{1,2}月\d{1,2}日)"
)
_IDENTIFIER_RE = re.compile(r"(?:oc|om|ou|cli|chat|thread)_[A-Za-z0-9]+", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_AMOUNT_RE = re.compile(r"(?:[¥￥]\s*)?\d+(?:\.\d+)?(?:[万亿]|[%％]|元)")


def entity_id(entity_type: str, value: str) -> str:
    digest = hashlib.sha256(f"{entity_type}\0{value}".encode("utf-8")).hexdigest()
    return digest


def extract_message_entities(
    message: dict[str, Any] | Any,
    chat_name: str = "",
    chat_id: str = "",
) -> list[dict[str, Any]]:
    """Extract deterministic entities without any external NLP dependency."""
    result: dict[str, dict[str, Any]] = {}
    text = str(message.get("content_normalized") or "").strip()
    group_value = chat_name.strip() or chat_id.strip() or "未命名群"

    _add(result, "person", str(message.get("sender_name") or "").strip(), 1)
    for mention in _parse_mentions(message):
        _add(
            result,
            "person",
            str(mention.get("name") or mention.get("display_name") or "").strip(),
            1,
        )
    _add(result, "group", group_value, 1)

    for value in _DEPARTMENT_RE.findall(text):
        _add(result, "department", value, 1)
    for value in _DATE_RE.findall(text):
        _add(result, "date", value.replace("/", "-"), 1)
    for value in _IDENTIFIER_RE.findall(text):
        _add(result, "identifier", value.lower(), 1)
    for value in _URL_RE.findall(text):
        _add(result, "url", value, 1)
    for value in _AMOUNT_RE.findall(text):
        _add(result, "amount", value, 1)

    return list(result.values())


def reply_to_message_id(message: dict[str, Any] | Any) -> str | None:
    for key in ("reply_to", "reply_message_id"):
        value = message.get(key)
        if value:
            return str(value)
    raw = message.get("raw_json")
    if not raw:
        return None
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    for key in ("reply_to", "reply_message_id"):
        if parsed.get(key):
            return str(parsed[key])
    reply = parsed.get("reply")
    if isinstance(reply, dict) and reply.get("message_id"):
        return str(reply["message_id"])
    return None


def _parse_mentions(message: dict[str, Any] | Any) -> list[dict[str, Any]]:
    raw = message.get("mentions")
    if raw is None:
        raw = message.get("mentions_json")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _add(
    result: dict[str, dict[str, Any]],
    entity_type: str,
    value: str,
    occurrence: int,
) -> None:
    value = value.strip()
    if not value:
        return
    key = entity_id(entity_type, value)
    current = result.get(key)
    if current is None:
        result[key] = {
            "entity_id": key,
            "entity_type": entity_type,
            "value": value,
            "canonical": value,
            "occurrence": occurrence,
        }
    else:
        current["occurrence"] += occurrence
