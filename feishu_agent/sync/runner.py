from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from feishu_agent.database.db import Database, iso_now
from feishu_agent.feishu.client import FeishuClient


def to_start_iso(value: str) -> str:
    text = value.strip().replace(" ", "T")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone(timedelta(hours=8)))
    return parsed.astimezone().isoformat(timespec="seconds")


class SyncRunner:
    def __init__(
        self,
        client: FeishuClient,
        db: Database,
        identity: str = "user",
    ) -> None:
        self.client = client
        self.db = db
        self.identity = identity
        self._sync_lock = threading.Lock()

    def sync_all(
        self,
        chat_ids: list[str] | None = None,
        full: bool = False,
    ) -> dict[str, Any]:
        with self._sync_lock:
            chats = self.client.list_chats(identity=self.identity)
            result: dict[str, Any] = {
                "identity": self.identity,
                "chats_scanned": len(chats),
                "messages_new": 0,
                "errors": [],
            }
            for chat in chats:
                chat_id = chat.get("chat_id")
                if not chat_id:
                    continue
                if chat_ids and chat_id not in chat_ids:
                    continue
                self.db.upsert_chat(chat)
                try:
                    result["messages_new"] += self.sync_chat(chat_id, full=full)
                except Exception as exc:  # keep one bad chat from blocking the rest
                    message = str(exc)
                    result["errors"].append({"chat_id": chat_id, "error": message})
                    self.db.set_sync_state(chat_id, status="error", error=message)
            return result

    def sync_chat(self, chat_id: str, full: bool = False) -> int:
        state = self.db.get_sync_state(chat_id)
        start = None
        if not full and state and state.get("last_message_time"):
            start = to_start_iso(state["last_message_time"])

        messages = self.client.list_messages(
            chat_id,
            identity=self.identity,
            order="asc",
            start=start,
        )

        new_count = 0
        for msg in messages:
            message_id = msg.get("message_id")
            if not message_id:
                continue
            is_new = not self.db.message_exists(message_id)
            # Upsert always, so edits and recalls are reflected locally too.
            self.db.upsert_message(msg, iso_now())
            if is_new:
                new_count += 1

        last = (
            max(
                messages,
                key=lambda m: (
                    m.get("create_time") or "",
                    m.get("message_position") or "",
                ),
            )
            if messages
            else None
        )
        self.db.set_sync_state(
            chat_id,
            last_message_id=last.get("message_id") if last else None,
            last_message_time=last.get("create_time") if last else None,
            status="ok",
        )
        self.db.touch_chat_sync(chat_id)
        return new_count
