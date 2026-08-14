"""M4 Agent 工具注册表。

所有工具都面向同步/索引/摘要共用的 SQLite 仓库执行，因此规则模式和
LLM 模式共享同一层可追溯的证据数据。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from feishu_agent.config import Settings
from feishu_agent.database.db import Database
from feishu_agent.index.repository import IndexRepository
from feishu_agent.summary.repository import SummaryRepository


TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    # 各工具 schema 会原样传给 LLM 规划器，语义化描述便于模型做工具选择。
    "search": {
        "description": "按关键词检索已索引的群聊消息，返回带消息 ID、时间、发送者和群名的候选依据",
        "parameters": {
            "query": "string",
            "chat_ids": "array[string]",
            "limit": "integer",
        },
        "required": ["query"],
    },
    "messages": {
        "description": "直接按关键词或群范围查询本地消息，适合未建索引或需要最近消息的场景",
        "parameters": {
            "chat_id": "string",
            "keyword": "string",
            "limit": "integer",
            "order": "string",
        },
        "required": [],
    },
    "summary": {
        "description": "读取某群最新的结构化摘要（结论、依据、待办、来源消息）",
        "parameters": {"chat_id": "string"},
        "required": ["chat_id"],
    },
    "graph_entity": {
        "description": "查询知识图谱中的实体、邻居关系和提及消息",
        "parameters": {"keyword": "string"},
        "required": ["keyword"],
    },
    "chat_list": {
        "description": "列出本地库中的群聊及群名",
        "parameters": {},
        "required": [],
    },
    "time_now": {
        "description": "返回当前服务器时间",
        "parameters": {},
        "required": [],
    },
}


@dataclass
class ToolResult:
    """工具执行的规范化结果，items 供证据引用使用。"""

    ok: bool
    items: list[dict[str, Any]] = field(default_factory=list)
    raw: Any = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典，方便写入 trace。"""
        return {
            "ok": self.ok,
            "items": self.items,
            "raw": self.raw,
            "error": self.error,
        }


class ToolRegistry:
    """按工具名解析并执行内置工具；每次执行都使用全新的数据库实例。"""

    def __init__(self, db_factory, settings: Settings | None = None) -> None:
        self.db_factory = db_factory
        self.settings = settings or Settings()

    def schema(self) -> dict[str, dict[str, Any]]:
        """返回全部工具的定义 schema，供 LLM 规划器选择工具。"""
        return TOOL_SCHEMAS

    def execute(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> ToolResult:
        """按名称分发到 _tool_* 处理器，未知工具与运行异常统一转成失败结果。"""
        args = dict(arguments or {})
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            return ToolResult(
                False,
                [],
                {"error": "tool_not_found", "name": name},
                "tool_not_found",
            )
        try:
            return handler(args)
        except Exception as exc:
            return ToolResult(False, [], {"error": str(exc)}, str(exc))

    def _db(self) -> Database:
        """从工厂创建数据库实例并确保表结构已初始化。"""
        db = self.db_factory()
        if hasattr(db, "init"):
            db.init()
        return db

    def _tool_search(self, args: dict[str, Any]) -> ToolResult:
        """调用混合检索，把命中的消息整理成带排名的证据条目。"""
        query = _string(args, "query")
        if not query:
            return ToolResult(
                False,
                [],
                {"error": "search_query_required"},
                "search_query_required",
            )
        limit = _int(args, "limit", self.settings.agent_max_evidence_items)
        raw = IndexRepository(self._db()).search(
            query,
            chat_ids=_chat_ids(args, "chat_ids") or None,
            limit=limit,
        )
        items: list[dict[str, Any]] = []
        for result in raw.get("results", []):
            chat_name = str(result.get("chat_name") or "")
            rank = int(result.get("rank") or 0)
            for message in result.get("messages", []):
                padded = dict(message)
                padded["chat_name"] = chat_name
                item = _evidence_item(padded, "search", rank)
                if item["message_id"]:
                    items.append(item)
        return ToolResult(True, items, raw)

    def _tool_messages(self, args: dict[str, Any]) -> ToolResult:
        """直接查询本地消息库，适合未建索引或需要最近消息的场景。"""
        db = self._db()
        limit = _int(args, "limit", self.settings.agent_max_evidence_items)
        rows = db.query_messages(
            chat_id=_string(args, "chat_id") or None,
            keyword=_string(args, "keyword") or None,
            limit=limit,
            order=_string(args, "order") or "desc",
        )
        valid = [row for row in rows if row.get("message_id")]
        names = _chat_names(db)
        items: list[dict[str, Any]] = []
        for row in valid:
            padded = dict(row)
            padded["chat_name"] = names.get(str(row.get("chat_id") or ""), "")
            item = _evidence_item(padded, "messages")
            if item["message_id"]:
                items.append(item)
        return ToolResult(True, items, {"total": len(valid), "messages": valid})

    def _tool_summary(self, args: dict[str, Any]) -> ToolResult:
        """读取群聊最新结构化摘要，并回查摘要引用的源消息作为证据。"""
        chat_id = _string(args, "chat_id")
        if not chat_id:
            return ToolResult(
                False,
                [],
                {"error": "chat_id_required"},
                "chat_id_required",
            )
        db = self._db()
        data = SummaryRepository(db, self.settings).get(chat_id)
        if data is None:
            return ToolResult(
                False,
                [],
                {"found": False, "chat_id": chat_id},
                "summary_not_found",
            )
        source_ids = {
            str(item) for item in (data.get("source_message_ids") or [])
        }
        names = _chat_names(db)
        items: list[dict[str, Any]] = []
        for row in db.query_messages(chat_id=chat_id, limit=500):
            if str(row.get("message_id") or "") not in source_ids:
                continue
            padded = dict(row)
            padded["chat_name"] = names.get(chat_id, "")
            item = _evidence_item(padded, "summary")
            if item["message_id"]:
                items.append(item)
        return ToolResult(
            True,
            items,
            {
                "found": True,
                "summary": data,
                "source_message_ids": sorted(source_ids),
            },
        )

    def _tool_graph_entity(self, args: dict[str, Any]) -> ToolResult:
        """查询知识图谱实体，命中时返回相关消息作为证据。"""
        keyword = _string(args, "keyword") or _string(args, "query")
        if not keyword:
            return ToolResult(
                False,
                [],
                {"error": "entity_keyword_required"},
                "entity_keyword_required",
            )
        raw = IndexRepository(self._db()).query_graph(keyword)
        if not raw.get("found"):
            reason = str(raw.get("error") or raw.get("message") or "entity_not_found")
            return ToolResult(False, [], raw, reason)
        items: list[dict[str, Any]] = []
        for message in raw.get("messages", []):
            item = _evidence_item(message, "graph")
            if item["message_id"]:
                items.append(item)
        return ToolResult(True, items, raw)

    def _tool_chat_list(self, args: dict[str, Any]) -> ToolResult:
        """列出本地已同步的群聊及群名。"""
        rows = self._db().list_chats()
        items: list[dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            item = _evidence_item(
                {
                    "message_id": "",
                    "chat_id": row.get("chat_id") or "",
                    "chat_name": row.get("name") or "",
                    "sender_name": "",
                    "create_time": "",
                    "content_normalized": str(row.get("description") or ""),
                },
                "chat_list",
                index,
            )
            items.append(item)
        return ToolResult(True, items, {"chats": rows})

    def _tool_time_now(self, args: dict[str, Any]) -> ToolResult:
        """返回当前服务器时间，供 LLM 做时间相关判断。"""
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        item = _evidence_item(
            {
                "message_id": "",
                "chat_id": "",
                "chat_name": "",
                "sender_name": "",
                "create_time": now,
                "content_normalized": f"当前时间：{now}",
            },
            "time_now",
            1,
        )
        return ToolResult(True, [item], {"now": now})


def _evidence_item(row: dict[str, Any], source: str, rank: int = 1) -> dict[str, Any]:
    """把不同来源的消息行统一成证据条目，截断过长的正文摘录。"""
    excerpt = str(
        row.get("content_normalized") or row.get("content") or row.get("excerpt") or ""
    )
    return {
        "message_id": str(row.get("message_id") or ""),
        "chat_id": str(row.get("chat_id") or ""),
        "chat_name": str(row.get("chat_name") or ""),
        "sender_name": str(row.get("sender_name") or ""),
        "create_time": str(row.get("create_time") or ""),
        "excerpt": excerpt[:800],
        "source": source,
        "rank": int(rank),
    }


def _string(args: dict[str, Any], key: str) -> str:
    """安全读取字符串参数，缺失或 None 时返回空串。"""
    value = args.get(key)
    return "" if value is None else str(value).strip()


def _int(args: dict[str, Any], key: str, default: int) -> int:
    """安全读取整数参数，非法值时回退到默认值且至少为 1。"""
    try:
        return max(1, int(args.get(key) or default))
    except (TypeError, ValueError):
        return max(1, int(default))


def _chat_ids(args: dict[str, Any], key: str) -> list[str]:
    """提取字符串列表参数并过滤空项。"""
    value = args.get(key)
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _chat_names(db: Database) -> dict[str, str]:
    """构建 chat_id 到群名的映射，供证据条目补全群名。"""
    try:
        return {
            str(row.get("chat_id") or ""): str(row.get("name") or "")
            for row in db.list_chats()
        }
    except Exception:
        return {}
