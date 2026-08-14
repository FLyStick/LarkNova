"""本地数据边界审计：按白名单与外部群策略检查需要清理的群聊数据。"""

from __future__ import annotations

from typing import Any

from feishu_agent.sync.runner import boundary_reason


def audit_local_db(
    db: Any,
    allowed_chat_ids: set[str] | None,
    allow_external: bool = False,
) -> dict[str, Any]:
    """审计本地群聊数据，返回违背边界策略、应被删除的群聊清单。

    会先剔除 chat_id 缺失的脏数据，再对每个群调用统一的边界判定函数，
    最终汇总待删除的消息总量与当前边界配置，方便人工确认后执行清理。
    """
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
    """按群聊 id 逐个删除本地数据，返回每个群删除后的统计结果。"""
    return [db.delete_chat(chat_id) for chat_id in chat_ids]
