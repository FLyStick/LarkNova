"""Shared fixtures for M2 index tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from feishu_agent.database.db import Database


def make_db(tmpdir: str) -> Database:
    db = Database(Path(tmpdir) / "agent.db")
    db.init()
    return db


def add_chat(db: Database, chat_id: str = "oc_a", name: str = "项目组") -> None:
    db.upsert_chat({"chat_id": chat_id, "name": name, "external": 0})


def message(
    message_id: str,
    chat_id: str = "oc_a",
    content: str = "body",
    create_time: str = "2026-08-11 10:00",
    position: int = 0,
    sender_name: str = "张三",
    sender_id: str = "ou_1",
    thread_id: str | None = None,
    msg_type: str = "text",
    mentions: list[dict[str, Any]] | None = None,
    deleted: bool = False,
    reply_message_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "message_id": message_id,
        "chat_id": chat_id,
        "msg_type": msg_type,
        "content": content,
        "create_time": create_time,
        "message_position": position,
        "sender": {"id": sender_id, "name": sender_name},
        "deleted": deleted,
        "thread_id": thread_id,
    }
    if mentions:
        payload["mentions"] = mentions
    if reply_message_id:
        payload["reply"] = {"message_id": reply_message_id}
    return payload
