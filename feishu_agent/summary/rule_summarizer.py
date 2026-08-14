"""确定性规则摘要器，作为易复现的 M3 基线实现。"""

from __future__ import annotations

import re
import time
from typing import Any

from feishu_agent.index.graph import extract_message_entities
from feishu_agent.summary.budget import build_context, estimate_tokens
from feishu_agent.summary.protocol import SummaryResult

_SENTENCE_END_RE = re.compile(r"(?<=[。！？!?；;])")
_DATE_RE = re.compile(
    r"(?:20\d{2}[-/年]\d{1,2}(?:[-/月]\d{1,2}日?)?|\d{1,2}月\d{1,2}日)"
)
_SIGNAL_KEYWORDS = (
    "结论",
    "决定",
    "确认",
    "已确认",
    "通过",
    "同意",
    "完成",
    "定稿",
    "结果",
    "明确",
)
_TODO_KEYWORDS = (
    "待办",
    "需要",
    "请",
    "确认",
    "截止",
    "提交",
    "跟进",
    "今天",
    "明天",
    "本周",
    "下周",
    "下午",
    "上午",
    "会议",
)
_IGNORE_SENDERS = {"系统", "system", "未知"}
_ENTITY_TYPES = {
    "person",
    "group",
    "department",
    "date",
    "identifier",
    "amount",
}


class RuleSummarizer:
    """从聊天块中规则化抽取结论、依据、待办、关键人与日期。"""

    mode = "rule"

    def __init__(self, settings: Any) -> None:
        self.settings = settings

    def summarize_chat(
        self,
        chat_id: str,
        chat_name: str,
        chunks: list[dict[str, Any]],
        now_iso: str,
    ) -> SummaryResult:
        """一次调用完成多字段抽取，并返回带来源与统计的摘要结果。"""
        started = time.perf_counter()
        # 先展平并去重消息，保证来源列表与摘要内容口径一致。
        messages = self._flatten_messages(chunks)
        source_message_ids = list(
            dict.fromkeys(str(msg["message_id"]) for msg in messages)
        )
        source_chunk_ids = sorted(
            {int(chunk["id"]) for chunk in chunks if chunk.get("id") is not None}
        )
        # 无消息的群不生成占位摘要，直接返回空结果。
        if not messages:
            return SummaryResult(
                conclusion="",
                evidence=[],
                todo=[],
                key_people=[],
                key_dates=[],
                entities=[],
                source_message_ids=[],
                source_chunk_ids=[],
            )

        context_lines = build_context(
            messages,
            self.settings.summary_max_chars,
        )
        conclusion = self._pick_conclusion(messages)
        evidence = self._evidence(context_lines)
        todo = self._todo_lines(messages)
        key_people = self._key_people(messages)
        key_dates = self._key_dates(messages)
        entities = self._entities(messages, chat_name, chat_id)
        output_text = "\n".join(
            [
                conclusion,
                *evidence,
                *todo,
                *key_people,
                *key_dates,
                *entities,
            ]
        )
        return SummaryResult(
            conclusion=conclusion,
            evidence=evidence,
            todo=todo,
            key_people=key_people,
            key_dates=key_dates,
            entities=entities,
            source_message_ids=source_message_ids,
            source_chunk_ids=source_chunk_ids,
            input_tokens=estimate_tokens("\n".join(context_lines)),
            output_tokens=estimate_tokens(output_text),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    @staticmethod
    def _flatten_messages(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """按 chunk 顺序展平消息并按 message_id 去重。"""
        messages: list[dict[str, Any]] = []
        seen: set[str] = set()
        for chunk in chunks:
            for msg in chunk.get("messages") or []:
                message_id = str(msg.get("message_id") or "")
                if not message_id or message_id in seen:
                    continue
                seen.add(message_id)
                messages.append(msg)
        return messages

    @staticmethod
    def _pick_conclusion(messages: list[dict[str, Any]]) -> str:
        """优先挑选含结论信号词的短句，最多合并两句作为结论。"""
        candidates: list[tuple[int, int, str, int]] = []
        for index, msg in enumerate(messages):
            content = str(msg.get("content_normalized") or "").strip()
            for sentence in _SENTENCE_END_RE.split(content):
                sentence = sentence.strip().strip("。！？!?；;")
                if len(sentence) < 8:
                    continue
                # 含信号词的句子优先，其次考虑更长的内容与更靠后的位置。
                signal = any(
                    keyword in sentence for keyword in _SIGNAL_KEYWORDS
                )
                candidates.append(
                    (2 if signal else 1, len(sentence), -index, sentence)
                )
        if not candidates:
            # 完全没有信号句时，退化为按长度挑选较长消息作为候选结论。
            candidates = [
                (1, len(content), -index, content)
                for index, msg in enumerate(messages)
                if (content := str(msg.get("content_normalized") or "").strip())
                and len(content) >= 8
            ]
        candidates.sort(reverse=True)
        picked = [item[3] for item in candidates[:2]]
        if not picked:
            return ""
        # 用 dict.fromkeys 去重，避免两句重复内容影响可读性。
        conclusion = "；".join(dict.fromkeys(picked))
        if len(conclusion) > 220:
            conclusion = conclusion[:220] + "..."
        return conclusion

    @staticmethod
    def _evidence(context_lines: list[str]) -> list[str]:
        """从构建好的上下文中选取一定数量不重复的长行作为依据。"""
        seen: set[str] = set()
        result: list[str] = []
        for line in context_lines:
            if len(line) < 12 or line in seen:
                continue
            seen.add(line)
            result.append(line)
            if len(result) >= 8:
                break
        return result

    @staticmethod
    def _todo_lines(messages: list[dict[str, Any]]) -> list[str]:
        """筛选含待办关键词的消息，并附加时间与发送者前缀。"""
        result: list[str] = []
        seen: set[str] = set()
        for msg in messages:
            content = str(msg.get("content_normalized") or "").strip()
            if (
                len(content) < 4
                or not any(keyword in content for keyword in _TODO_KEYWORDS)
                or content in seen
            ):
                continue
            seen.add(content)
            raw_time = str(msg.get("create_time") or "")
            time_part = raw_time[11:19] if len(raw_time) >= 19 else ""
            sender = str(msg.get("sender_name") or "未知").strip() or "未知"
            prefix = f"[{time_part}] {sender}: " if time_part else f"{sender}: "
            result.append(prefix + content)
            if len(result) >= 6:
                break
        return result

    @staticmethod
    def _key_people(messages: list[dict[str, Any]]) -> list[str]:
        """收集非系统发送者姓名，保持首次出现顺序并去重。"""
        return list(
            dict.fromkeys(
                str(msg.get("sender_name") or "").strip()
                for msg in messages
                if str(msg.get("sender_name") or "").strip()
                and str(msg.get("sender_name") or "").strip() not in _IGNORE_SENDERS
            )
        )

    @staticmethod
    def _key_dates(messages: list[dict[str, Any]]) -> list[str]:
        """从正文和发送时间中抽取日期，最多保留 10 个。"""
        result: list[str] = []
        for msg in messages:
            content = str(msg.get("content_normalized") or "")
            for value in _DATE_RE.findall(content):
                value = value.replace("/", "-")
                if value not in result:
                    result.append(value)
            create_time = str(msg.get("create_time") or "")
            if len(create_time) >= 10 and create_time[4] in "-年":
                date_part = create_time[:10].replace("年", "-").replace("月", "-")
                if date_part not in result and date_part[:1].isdigit():
                    result.append(date_part)
        return result[:10]

    @staticmethod
    def _entities(
        messages: list[dict[str, Any]],
        chat_name: str,
        chat_id: str,
    ) -> list[str]:
        """复用知识图谱实体抽取，过滤类型白名单与重复项。"""
        result: list[str] = []
        seen: set[str] = set()
        for msg in messages:
            for entity in extract_message_entities(
                msg,
                chat_name=chat_name,
                chat_id=chat_id,
            ):
                entity_type = str(entity.get("entity_type") or "")
                value = str(entity.get("value") or "").strip()
                if (
                    not value
                    or entity_type not in _ENTITY_TYPES
                    or value in seen
                ):
                    continue
                seen.add(value)
                result.append(value)
                if len(result) >= 12:
                    return result
        return result
