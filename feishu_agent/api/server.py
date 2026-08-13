from __future__ import annotations

import json
import threading
import time
import urllib.parse
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from feishu_agent.agent.protocol import AgentConfigError
from feishu_agent.agent.repository import AgentRepository
from feishu_agent.index.repository import IndexRepository
from feishu_agent.summary.repository import SummaryRepository
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
        if route.startswith("/api/agent/"):
            if not self._agent_authorized():
                self._send_json({"ok": False, "error": "unauthorized"}, status=401)
                return
            if self._rate_limited():
                self._send_json(
                    {"ok": False, "error": "rate_limit_exceeded"},
                    status=429,
                )
                return
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
        elif route == "/api/search":
            query = urllib.parse.parse_qs(parsed.query)
            self._send_json(
                {
                    "ok": True,
                    **self._new_index().search(
                        _first(query, "q") or "",
                        chat_ids=query.get("chat_id") or None,
                        limit=_first_int(query, "limit", 10),
                    ),
                }
            )
        elif route == "/api/graph/entities":
            query = urllib.parse.parse_qs(parsed.query)
            self._send_json(
                {
                    "ok": True,
                    "entities": self._new_index().list_entities(
                        entity_type=_first(query, "type"),
                        q=_first(query, "q"),
                        limit=_first_int(query, "limit", 50),
                    ),
                }
            )
        elif route == "/api/graph/entity":
            query = urllib.parse.parse_qs(parsed.query)
            self._send_json(
                {
                    "ok": True,
                    **self._new_index().query_graph(_first(query, "q") or ""),
                }
            )
        elif route.startswith("/api/graph/entity/"):
            entity_id = urllib.parse.unquote(route.split("/", 4)[-1])
            self._send_json(
                {"ok": True, **self._new_index().query_graph(entity_id)}
            )
        elif route == "/api/index/status":
            self._send_json({"ok": True, **self._new_index().status()})
        elif route == "/api/summaries":
            query = urllib.parse.parse_qs(parsed.query)
            items = self._new_summary().list_summaries(
                chat_ids=query.get("chat_id") or None,
                period_start=_first(query, "period_start"),
                period_end=_first(query, "period_end"),
                limit=_first_int(query, "limit", 50),
            )
            self._send_json({"ok": True, "count": len(items), "summaries": items})
        elif route == "/api/summaries/status":
            self._send_json({"ok": True, **self._new_summary().status()})
        elif route == "/api/agent/runs":
            query = urllib.parse.parse_qs(parsed.query)
            runs = AgentRepository(self._new_db()).list_runs(
                limit=_first_int(query, "limit", 20)
            )
            self._send_json({"ok": True, "runs": runs})
        elif route == "/api/agent/stats":
            self._send_json(
                {"ok": True, **AgentRepository(self._new_db()).stats()}
            )
        elif route.startswith("/api/agent/runs/"):
            run_id = urllib.parse.unquote(route.split("/", 4)[-1])
            run = AgentRepository(self._new_db()).get(run_id)
            if run is None:
                self._send_json(
                    {"ok": False, "error": "run_not_found"},
                    status=404,
                )
            else:
                self._send_json({"ok": True, "run": run})
        else:
            self._send_json({"ok": False, "error": "not found"}, status=404)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        request = self._read_json_body()
        if parsed.path.startswith("/api/agent/"):
            if not self._agent_authorized():
                self._send_json({"ok": False, "error": "unauthorized"}, status=401)
                return
            if self._rate_limited():
                self._send_json(
                    {"ok": False, "error": "rate_limit_exceeded"},
                    status=429,
                )
                return
        if parsed.path == "/api/sync":
            try:
                result = self.server.runner.sync_all(full=bool(request.get("full")))
                self._send_json({"ok": True, **result})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=500)
        elif parsed.path == "/api/index/rebuild":
            try:
                result = self._new_index().rebuild(
                    allow_external=bool(request.get("allow_external")),
                    chat_ids=_chat_ids(request),
                    allowed_chat_ids=self.server.runner.allowed_chat_ids,
                )
                self._send_json({"ok": True, **result})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=500)
        elif parsed.path == "/api/index/incremental":
            try:
                result = self._new_index().incremental(
                    chat_ids=_chat_ids(request),
                    allowed_chat_ids=self.server.runner.allowed_chat_ids,
                )
                self._send_json({"ok": True, **result})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=500)
        elif parsed.path == "/api/summaries/rebuild":
            try:
                result = self._new_summary().rebuild(
                    chat_ids=_chat_ids(request),
                    allowed_chat_ids=self.server.runner.allowed_chat_ids,
                    include_external=bool(request.get("allow_external")),
                    mode=str(request.get("mode") or "rule"),
                )
                self._send_json({"ok": True, **result})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=500)
        elif parsed.path == "/api/summaries/incremental":
            try:
                result = self._new_summary().incremental(
                    chat_ids=_chat_ids(request),
                    allowed_chat_ids=self.server.runner.allowed_chat_ids,
                    mode=str(request.get("mode") or "rule"),
                )
                self._send_json({"ok": True, **result})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=500)
        elif parsed.path == "/api/agent/ask":
            try:
                agent = self.server.agent_factory()
                trace = agent.ask(
                    question=str(request.get("question") or ""),
                    mode=str(request.get("mode") or "auto"),
                    chat_ids=_chat_ids(request),
                )
                self._send_json({"ok": True, "trace": trace.to_dict()})
            except AgentConfigError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=500)
        else:
            self._send_json({"ok": False, "error": "not found"}, status=404)

    def _read_json_body(self) -> dict[str, Any]:
        raw = b""
        length = int(self.headers.get("Content-Length") or 0)
        if length > 0:
            raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

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

    def _new_index(self) -> IndexRepository:
        factory = getattr(self.server, "index_factory", None)
        if factory is not None:
            return factory()
        return IndexRepository(self._new_db())

    def _new_summary(self) -> SummaryRepository:
        factory = getattr(self.server, "summary_factory", None)
        if factory is not None:
            return factory()
        return SummaryRepository(self._new_db())

    def _agent_authorized(self) -> bool:
        token = str(getattr(self.server, "api_token", "") or "")
        if not token:
            return True
        header = str(self.headers.get("Authorization") or "")
        if header.startswith("Bearer "):
            return header[len("Bearer ") :].strip() == token
        return str(self.headers.get("X-API-Token") or "").strip() == token

    def _rate_limited(self) -> bool:
        per_minute = int(getattr(self.server, "rate_limit_per_min", 0) or 0)
        if per_minute <= 0:
            return False
        now = time.monotonic()
        with self.server.rate_lock:
            hits = self.server.rate_hits
            while hits and now - hits[0] >= 60:
                hits.popleft()
            if len(hits) >= per_minute:
                return True
            hits.append(now)
        return False

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

    def __init__(
        self,
        addr,
        runner: SyncRunner,
        db_factory,
        index_factory=None,
        summary_factory=None,
        agent_factory=None,
        api_token="",
        rate_limit_per_min=0,
    ) -> None:
        self.runner = runner
        self.db_factory = db_factory
        self.index_factory = index_factory
        self.summary_factory = summary_factory
        self.agent_factory = agent_factory
        self.api_token = api_token
        self.rate_limit_per_min = max(0, int(rate_limit_per_min or 0))
        self.rate_hits: deque[float] = deque()
        self.rate_lock = threading.Lock()
        super().__init__(addr, ApiHandler)


def _chat_ids(request: dict[str, Any]) -> list[str] | None:
    value = request.get("chat_ids")
    if not isinstance(value, list):
        return None
    return [str(item) for item in value if item]


def create_server(
    addr,
    runner: SyncRunner,
    db_factory,
    index_factory=None,
    summary_factory=None,
    agent_factory=None,
    api_token="",
    rate_limit_per_min=0,
) -> FeishuAgentServer:
    return FeishuAgentServer(
        addr,
        runner,
        db_factory,
        index_factory,
        summary_factory,
        agent_factory,
        api_token,
        rate_limit_per_min,
    )
