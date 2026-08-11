from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Any


class FeishuError(RuntimeError):
    """Raised when lark-cli returns a non-ok response."""

    def __init__(self, code: Any, message: str, raw: dict[str, Any]) -> None:
        self.code = code
        self.raw = raw
        super().__init__(message)


class FeishuClient:
    """Thin wrapper around the locally installed lark-cli."""

    def __init__(
        self,
        node: str = "node",
        cli_js: str = "",
        identity: str = "user",
        timeout: int = 180,
    ) -> None:
        self.node = node
        self.cli_js = cli_js
        self.identity = identity
        self.timeout = timeout

    def run(self, args: list[str], retries: int = 2) -> dict[str, Any]:
        env = os.environ.copy()
        env["LARKSUITE_CLI_NO_UPDATE_NOTIFIER"] = "1"
        env["LARKSUITE_CLI_NO_SKILLS_NOTIFIER"] = "1"
        last_error: FeishuError | None = None
        for attempt in range(retries + 1):
            proc = subprocess.run(
                [self.node, self.cli_js, *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=self.timeout,
            )
            payload = self._parse_output(proc.stdout) or self._parse_output(proc.stderr)
            if payload is None:
                raise FeishuError(
                    -1,
                    f"lark-cli returned no JSON (exit {proc.returncode})",
                    {"stdout": (proc.stdout or "")[-2000:], "stderr": (proc.stderr or "")[-2000:]},
                )
            if payload.get("ok"):
                return payload
            err = payload.get("error") or {}
            message = err.get("message") or "unknown lark-cli error"
            error = FeishuError(err.get("code"), str(message), payload)
            if not self._is_transient(error) or attempt >= retries:
                raise error
            last_error = error
            time.sleep(1 + attempt)
        raise last_error  # pragma: no cover - loop always raises above

    @staticmethod
    def _is_transient(error: FeishuError) -> bool:
        err_type = (error.raw.get("error") or {}).get("type")
        message = str(error).lower()
        return err_type == "network" or "read tcp" in message or "connection reset" in message

    @staticmethod
    def _parse_output(text: str) -> dict[str, Any] | None:
        text = (text or "").strip()
        if not text:
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def list_chats(self, identity: str | None = None) -> list[dict[str, Any]]:
        who = identity or self.identity
        args = [
            "im",
            "+chat-list",
            "--as",
            who,
            "--sort",
            "active_time",
            "--page-size",
            "100",
            "--page-all",
            "--format",
            "json",
        ]
        data = self.run(args)
        return data.get("data", {}).get("chats") or []

    def list_messages(
        self,
        chat_id: str,
        identity: str | None = None,
        order: str = "asc",
        page_size: int = 50,
        start: str | None = None,
        end: str | None = None,
        page_all: bool = True,
    ) -> list[dict[str, Any]]:
        who = identity or self.identity
        args = [
            "im",
            "+chat-messages-list",
            "--as",
            who,
            "--chat-id",
            chat_id,
            "--order",
            order,
            "--page-size",
            str(page_size),
            "--no-reactions",
            "--format",
            "json",
        ]
        if page_all:
            args += ["--page-all", "--page-limit", "1000", "--page-delay", "0"]
        if start:
            args += ["--start", start]
        if end:
            args += ["--end", end]
        data = self.run(args)
        return data.get("data", {}).get("messages") or []
