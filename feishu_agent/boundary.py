from __future__ import annotations

from typing import Any

from feishu_agent.sync.runner import boundary_reason


def audit_local_db(
    db: Any,
    allowed_chat_ids: set[str] | None,
    allow_external: bool = False,
) -> dict[str, Any]:
    """Audit local chats against whitelist and external-chat policy."""
    chats_to_remove: list[dict[str, Any]] = []
    for chat in db.list_chats():
        chat_id = str(chat.get("chat_id") or "")
        if not chat_id:
            chats_to_remove.append(
                {
                    "chat_id": "",
                    "chat_name": chat.get("name") or "",
                    "external": 1 if chat.get("external") else 0,
                    "messages": 0,
                    "reason": "missing_chat_id",
                }
            )
            continue
        reason = boundary_reason(
            chat_id,
            bool(chat.get("external")),
            allowed_chat_ids,
            allow_external,
        )
        if reason:
            chats_to_remove.append(
                {
                    "chat_id": chat_id,
                    "chat_name": chat.get("name") or "",
                    "external": 1 if chat.get("external") else 0,
                    "messages": db.count_messages(chat_id),
                    "reason": reason,
                }
            )
    return {
        "chats_checked": len(db.list_chats()),
        "chats_to_remove": chats_to_remove,
        "messages_to_remove": sum(item["messages"] for item in chats_to_remove),
        "boundary": {
            "allow_external": allow_external,
            "whitelist": sorted(allowed_chat_ids) if allowed_chat_ids else [],
        },
    }


def prune_local_db(db: Any, chat_ids: list[str]) -> list[dict[str, int]]:
    return [db.delete_chat(chat_id) for chat_id in chat_ids]