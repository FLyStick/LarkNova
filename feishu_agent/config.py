from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

def _load_dotenv(path: Path) -> None:
    """Load KEY=VALUE pairs without overriding variables already in env."""
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8-sig")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


_load_dotenv(PROJECT_ROOT / ".env")


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


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
        raw_allowed = os.environ.get("FEISHU_AGENT_ALLOWED_CHAT_IDS", "").strip()
        self.allowed_chat_ids: set[str] | None = (
            {part.strip() for part in raw_allowed.replace(";", ",").split(",") if part.strip()}
            if raw_allowed
            else None
        )
        self.allow_external_chats = _parse_bool(
            os.environ.get("FEISHU_AGENT_ALLOW_EXTERNAL_CHATS", "0")
        )
        self.sync_interval = int(os.environ.get("FEISHU_AGENT_SYNC_INTERVAL", "60"))
        self.sync_timeout = int(os.environ.get("FEISHU_AGENT_SYNC_TIMEOUT", "180"))
        self.host = os.environ.get("FEISHU_AGENT_HOST", "127.0.0.1")
        self.port = int(os.environ.get("FEISHU_AGENT_PORT", "8080"))
        # M3 summary budgets. Rule mode is the default baseline; LLM mode is
        # an optional upgrade through any OpenAI-compatible /chat/completions
        # endpoint.
        self.summary_max_chars = int(
            os.environ.get("FEISHU_AGENT_SUMMARY_MAX_CHARS", "4000")
        )
        self.summary_input_token_budget = int(
            os.environ.get("FEISHU_AGENT_SUMMARY_INPUT_TOKEN_BUDGET", "6000")
        )
        self.summary_output_token_budget = int(
            os.environ.get("FEISHU_AGENT_SUMMARY_OUTPUT_TOKEN_BUDGET", "1200")
        )
        self.summary_min_new_messages = int(
            os.environ.get("FEISHU_AGENT_SUMMARY_MIN_NEW_MESSAGES", "1")
        )
        self.llm_api_url = os.environ.get("FEISHU_AGENT_LLM_API_URL", "").strip()
        self.llm_api_key = os.environ.get("FEISHU_AGENT_LLM_API_KEY", "").strip()
        self.llm_model = os.environ.get("FEISHU_AGENT_LLM_MODEL", "").strip()
        self.llm_timeout = int(os.environ.get("FEISHU_AGENT_LLM_TIMEOUT", "60"))
