from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings:
    """Runtime settings loaded from environment variables."""

    def __init__(self) -> None:
        self.db_path = Path(
            os.environ.get("FEISHU_AGENT_DB", str(PROJECT_ROOT / "data" / "agent.db"))
        )
        self.node = os.environ.get("LARK_NODE", "node")
        self.lark_cli_js = os.environ.get(
            "LARK_CLI_JS",
            r"D:\App\nodejs\node_global\node_modules\@larksuite\cli\scripts\run.js",
        )
        # Current MVP uses user identity because the bot reading messages is
        # blocked by a missing app scope (230027). Switch to bot after enabling
        # im:message:readonly in the Feishu developer console.
        self.identity = os.environ.get("LARK_IDENTITY", "user")
        self.sync_interval = int(os.environ.get("FEISHU_AGENT_SYNC_INTERVAL", "60"))
        self.sync_timeout = int(os.environ.get("FEISHU_AGENT_SYNC_TIMEOUT", "180"))
        self.host = os.environ.get("FEISHU_AGENT_HOST", "127.0.0.1")
        self.port = int(os.environ.get("FEISHU_AGENT_PORT", "8080"))
