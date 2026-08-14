"""飞书开放平台客户端：封装 lark-cli 的群聊与消息读取命令。"""

from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Any


class FeishuError(RuntimeError):
    """lark-cli 返回非 ok 或无法解析结果时抛出的异常。"""

    def __init__(self, code: Any, message: str, raw: dict[str, Any]) -> None:
        """记录错误码与原始返回，方便上层根据 code 判断权限等场景。"""
        self.code = code
        self.raw = raw
        super().__init__(message)


class FeishuClient:
    """本地 lark-cli 的轻量封装，负责调用群聊与消息读取命令。"""

    def __init__(
        self,
        node: str = "node",
        cli_js: str = "",
        identity: str = "user",
        timeout: int = 180,
    ) -> None:
        """初始化 node/cli 路径、身份标识与命令超时时间。"""
        self.node = node
        self.cli_js = cli_js
        self.identity = identity
        self.timeout = timeout

    def run(self, args: list[str], retries: int = 2) -> dict[str, Any]:
        """执行一条 lark-cli 命令，解析 JSON 并对网络类错误做有限重试。"""
        env = os.environ.copy()
        # 关闭 CLI 的更新与技能类提示，保证 stdout 稳定为可解析的 JSON。
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
        """判断错误是否为网络抖动可重试类型。"""
        err_type = (error.raw.get("error") or {}).get("type")
        message = str(error).lower()
        return err_type == "network" or "read tcp" in message or "connection reset" in message

    @staticmethod
    def _parse_output(text: str) -> dict[str, Any] | None:
        """宽松解析 CLI 输出为 JSON 对象，失败返回 None 不抛异常。"""
        text = (text or "").strip()
        if not text:
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def list_chats(self, identity: str | None = None) -> list[dict[str, Any]]:
        """按活跃时间倒序列出当前身份可见的全部群聊。"""
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
        """读取指定群的消息，支持顺序、分页、时间窗和身份切换。"""
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
            # 全量拉取时由 CLI 遍历剩余分页，内部限制单页 1000 条。
            args += ["--page-all", "--page-limit", "1000", "--page-delay", "0"]
        if start:
            args += ["--start", start]
        if end:
            args += ["--end", end]
        data = self.run(args)
        return data.get("data", {}).get("messages") or []
