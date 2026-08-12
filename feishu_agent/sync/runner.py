from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from feishu_agent.database.db import Database, iso_now
from feishu_agent.feishu.client import FeishuClient
from feishu_agent.index.repository import IndexRepository


def boundary_reason(
    chat_id: str,
    external: bool,
    allowed_chat_ids: set[str] | None,
    allow_external: bool,
) -> str | None:
    """Return a skip reason when a chat must not enter the local database."""
    if allowed_chat_ids is not None and chat_id not in allowed_chat_ids:
        return "not_in_whitelist"
    if not allow_external and external:
        return "external_chat"
    return None


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
        allowed_chat_ids: set[str] | None = None,
        allow_external: bool = False,
    ) -> None:
        self.client = client
        self.db = db
        self.identity = identity
        self.allowed_chat_ids = set(allowed_chat_ids) if allowed_chat_ids else None
        self.allow_external = allow_external
        self._sync_lock = threading.Lock()

    def sync_all(
        self,
        chat_ids: list[str] | None = None,
        full: bool = False,
    ) -> dict[str, Any]:
        with self._sync_lock:
            started = datetime.now().astimezone()
            result: dict[str, Any] = {
                "identity": self.identity,
                "mode": "full" if full else "incremental",
                "started_at": started.isoformat(timespec="seconds"),
                "chats_scanned": 0,
                "chats_allowed": 0,
                "chats_skipped": [],
                "chats_failed": 0,
                "messages_new": 0,
                "messages_updated": 0,
                "messages_deleted": 0,
                "messages_restored": 0,
                "errors": [],
                "index": None,
                "boundary": {
                    "allow_external": self.allow_external,
                    "whitelist": sorted(self.allowed_chat_ids) if self.allowed_chat_ids is not None else [],
                },
            }
            try:
                chats = self.client.list_chats(identity=self.identity)
            except Exception as exc:
                result["chats_failed"] = 1
                result["errors"].append(
                    {"chat_id": None, "error": str(exc), "stage": "chat_list"}
                )
                result["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
                result["duration_ms"] = int(
                    (datetime.now().astimezone() - started).total_seconds() * 1000
                )
                self.db.record_sync_run(result)
                return result
            result["chats_scanned"] = len(chats)
            for chat in chats:
                chat_id = chat.get("chat_id")
                if not chat_id:
                    result["chats_skipped"].append(
                        {"chat_id": None, "chat_name": chat.get("name", ""), "reason": "missing_chat_id"}
                    )
                    continue
                if chat_ids is not None and chat_id not in chat_ids:
                    continue
                reason = boundary_reason(
                    chat_id,
                    bool(chat.get("external")),
                    self.allowed_chat_ids,
                    self.allow_external,
                )
                if reason:
                    result["chats_skipped"].append(
                        {"chat_id": chat_id, "chat_name": chat.get("name", ""), "reason": reason}
                    )
                    continue
                result["chats_allowed"] += 1
                self.db.upsert_chat(chat)
                try:
                    counts = self.sync_chat(chat_id, full=full)
                    result["messages_new"] += counts.get("new", 0)
                    result["messages_updated"] += counts.get("updated", 0)
                    result["messages_deleted"] += counts.get("deleted", 0)
                    result["messages_restored"] += counts.get("restored", 0)
                except Exception as exc:  # keep one bad chat from blocking the rest
                    message = str(exc)
                    result["errors"].append({"chat_id": chat_id, "error": message})
                    self.db.set_sync_state(
                        chat_id, status="error", error=message, preserve_cursor=True
                    )
            result["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            result["duration_ms"] = int(
                (datetime.now().astimezone() - started).total_seconds() * 1000
            )
            result["chats_failed"] = len(result["errors"])
            result["index"] = self._incremental_index(chat_ids)
            self.db.record_sync_run(result)
            return result

    def _incremental_index(self, chat_ids: list[str] | None) -> dict[str, Any]:
        """Refresh the derived index after sync without blocking sync failures."""
        try:
            return IndexRepository(self.db).incremental(
                chat_ids=chat_ids,
                allowed_chat_ids=self.allowed_chat_ids,
            )
        except Exception as exc:
            return {"mode": "incremental", "built": False, "error": str(exc)}

    def sync_chat(self, chat_id: str, full: bool = False) -> dict[str, Any]:
        started = datetime.now().astimezone()
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

        valid = [msg for msg in messages if msg.get("message_id")]
        counts: dict[str, Any] = {
            "chat_id": chat_id,
            "status": "ok",
            "messages_fetched": len(messages),
            "messages_matched": len(valid),
            "new": 0,
            "updated": 0,
            "deleted": 0,
            "restored": 0,
            "unchanged": 0,
        }
        for msg in valid:
            outcome = self.db.upsert_message(msg, iso_now())
            kind = outcome.get("change_kind")
            if outcome.get("status") == "created":
                counts["new"] += 1
            elif kind == "recalled":
                counts["deleted"] += 1
            elif kind == "restored":
                counts["restored"] += 1
            elif outcome.get("status") == "updated":
                counts["updated"] += 1
            else:
                counts["unchanged"] += 1

        if valid:
            last = max(
                valid,
                key=lambda m: (
                    m.get("create_time") or "",
                    m.get("message_position") or "",
                ),
            )
            self.db.set_sync_state(
                chat_id,
                last_message_id=last.get("message_id"),
                last_message_time=last.get("create_time"),
                status="ok",
                error=None,
            )
        else:
            self.db.set_sync_state(
                chat_id, status="ok", error=None, preserve_cursor=True
            )
        counts["duration_ms"] = int(
            (datetime.now().astimezone() - started).total_seconds() * 1000
        )
        self.db.touch_chat_sync(chat_id)
        return counts
