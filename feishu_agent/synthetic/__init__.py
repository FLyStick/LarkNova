"""M5 合成语料包：生成可复现的多部门对话测试数据。"""

from feishu_agent.synthetic.seed import (
    CHAT_DEFS,
    GOLDEN_MESSAGE_IDS,
    GOLDEN_REF_SPECS,
    PEOPLE,
    TOTAL_MESSAGES,
    TOPIC_DEFS,
    build_messages,
    message_id_for,
    seed_database,
    synthetic_status,
)

__all__ = [
    "CHAT_DEFS",
    "GOLDEN_MESSAGE_IDS",
    "GOLDEN_REF_SPECS",
    "PEOPLE",
    "TOTAL_MESSAGES",
    "TOPIC_DEFS",
    "build_messages",
    "message_id_for",
    "seed_database",
    "synthetic_status",
]
