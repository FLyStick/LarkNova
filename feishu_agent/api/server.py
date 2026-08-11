from __future__ import annotations

import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from feishu_agent.sync.runner import SyncRunner


def _first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def _first_int(query: dict[str, list[str]], key: str, default: int) -> int:
    try:
        return int(_first(query, key) or default)
    except (TypeError, ValueError):
        return default


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "FeishuAgent/0.1"

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        route = parsed.path
        if route == "/health":
            self._send_json(
                {
                    "ok": True,
                    "service": "feishu-agent",
                    "identity": self.server.runner.identity,
                    "stats": self._new_db().stats(),
                }
            )
        elif route == "/api/chats":
            self._send_json({"ok": True, "chats": self._new_db().list_chats()})
        elif route == "/api/messages":
            self._send_json({"ok": True, "messages": self._query_messages(parsed.query)})
        elif route == "/api/stats":
            self._send_json({"ok": True, **self._new_db().stats()})
        elif route == "/api/metrics":
            query = urllib.parse.parse_qs(parsed.query)
            self._send_json(
                {
                    "ok": True,
                    **self._new_db().metrics(
                        limit=_first_int(query, "limit", 10)
                    ),
                }
            )
        elif route == "/api/sync-runs":
            query = urllib.parse.parse_qs(parsed.query)
            self._send_json(
                {
                    "ok": True,
                    "runs": self._new_db().recent_sync_runs(
                        limit=_first_int(query, "limit", 20)
                    ),
                }
            )
        elif route == "/api/message-versions":
            query = urllib.parse.parse_qs(parsed.query)
            self._send_json(
                {
                    "ok": True,
                    "versions": self._new_db().list_message_versions(
                        message_id=_first(query, "message_id"),
                        limit=_first_int(query, "limit", 100),
                    ),
                }
            )
        else:
            self._send_json({"ok": False, "error": "not found"}, status=404)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path != "/api/sync":
            self._send_json({"ok": False, "error": "not found"}, status=404)
            return
        raw = b""
        length = int(self.headers.get("Content-Length") or 0)
        if length > 0:
            raw = self.rfile.read(length)
        try:
            request = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            request = {}
        try:
            result = self.server.runner.sync_all(full=bool(request.get("full")))
            self._send_json({"ok": True, **result})
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=500)

    def _query_messages(self, raw_query: str) -> list[dict[str, Any]]:
        query = urllib.parse.parse_qs(raw_query)
        db = self._new_db()
        return db.query_messages(
            chat_id=_first(query, "chat_id"),
            keyword=_first(query, "q"),
            msg_type=_first(query, "msg_type"),
            sender_id=_first(query, "sender_id"),
            limit=int(_first(query, "limit") or 100),
            order=_first(query, "order") or "asc",
        )

    def _new_db(self):
        return self.server.db_factory()

    def _send_json(self, obj: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        # Keep the MVP console quiet; uncomment for debugging.
        pass

class FeishuAgentServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, runner: SyncRunner, db_factory) -> None:
        self.runner = runner
        self.db_factory = db_factory
        super().__init__(addr, ApiHandler)


def create_server(addr, runner: SyncRunner, db_factory) -> FeishuAgentServer:
    return FeishuAgentServer(addr, runner, db_factory)
