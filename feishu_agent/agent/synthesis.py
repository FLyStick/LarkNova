"""通用确定性答案合成：按问题类型抽取证据要点，避免整段贴证据原文。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class SynthesisResult:
    """合成结果：最终答案与真正支撑答案的消息 id。"""

    answer: str
    cited_item_ids: list[str] = field(default_factory=list)


_KIND_MARKERS: tuple[str, ...] = (
    "馅",
    "味道",
    "价格",
    "金额",
    "预算",
    "日期",
    "时间",
    "负责人",
    "原因",
    "结果",
    "结论",
)

_RECENT_MARKERS: tuple[str, ...] = (
    "最近",
    "最新",
    "今天",
    "昨天",
    "本周",
    "刚才",
    "新消息",
)

_CONCISE_MARKERS: tuple[str, ...] = (
    "只告诉我",
    "只要",
    "只回答",
    "只输出",
    "只需要",
    "不需要其他",
    "不用解释",
    "不要其他",
    "别加",
    "简短",
    "一句话",
    "直接说",
    "简单说",
)

_TIME_MARKERS: tuple[str, ...] = (
    "什么时候",
    "什么时间",
    "几点",
    "哪天",
    "几号",
    "何时",
    "日期",
    "截止",
    "好久",
    "多久",
)

_PERSON_MARKERS: tuple[str, ...] = (
    "谁",
    "负责人",
    "交接人",
    "验收人",
    "复核人",
    "联系人",
    "陪同",
    "接待",
)

_AMOUNT_MARKERS: tuple[str, ...] = (
    "多少钱",
    "多少",
    "金额",
    "预算",
    "报价",
    "价格",
    "占比",
    "几台",
    "几笔",
)

_BOOLEAN_MARKERS: tuple[str, ...] = (
    "是否",
    "是不是",
    "有没有",
)

_ATTRIBUTE_MARKERS: tuple[str, ...] = (
    "什么",
    "哪些",
    "为什么",
    "原因",
    "结论",
    "结果",
    "要求",
    "内容",
)

_QUESTION_MARKERS: tuple[str, ...] = (
    "什么时候",
    "什么时间",
    "什么原因",
    "为什么",
    "多少钱",
    "多少",
    "什么",
    "哪些",
    "几点",
    "哪天",
    "几号",
    "怎么",
    "如何",
    "谁",
    "是否",
    "是不是",
    "有没有",
)

_REMOVE_WORDS: tuple[str, ...] = (
    "请问",
    "你知道",
    "告诉我",
    "帮我查一下",
    "查一下",
    "什么时候",
    "什么时间",
    "什么原因",
    "为什么",
    "多少钱",
    "多少",
    "什么",
    "哪些",
    "几点",
    "哪天",
    "几号",
    "怎么",
    "如何",
    "是否",
    "是不是",
    "有没有",
    "应该",
    "安排",
    "相关",
    "的消息",
    "的信息",
    "呢",
    "吗",
    "啊",
    "的",
    "了",
)

_DEFAULT_INTRO = "根据本地消息检索，找到以下相关依据："

_TIME_PHRASE_RE = re.compile(
    r"(?P<when>(?:今天|明天|后天|昨天|本周|下周|周[一二三四五六日天])"
    r"(?:\s*[（(][^）)\n]{1,40}[）)])?"
    r"(?:\s*(?:上午|中午|下午|晚上|凌晨))?)"
    r"\s*(?P<range>\d{1,2}[:：]\d{2}\s*[-—~至到]\s*\d{1,2}[:：]\d{2})"
)

_DATE_PHRASE_RE = re.compile(
    r"(?P<date>\d{1,2}月\d{1,2}日(?:\s*(?:\d{1,2}[:：]\d{2}))?)"
)

_SUPERSEDE_RE = re.compile(r"(作废|取消|以\s*[^。；]*\s*为准|另行通知|改期)")

_AMOUNT_VALUE_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:万元|元|万|千元|笔|台|套|个|次|G|GB|小时|分钟|秒|毫秒|ms|天|%|倍)"
)

_PROCEDURE_MARKERS: tuple[str, ...] = (
    "怎么",
    "如何",
    "怎么办",
    "处理",
    "措施",
    "方案",
)

_STRONG_DIRECTIVE_MARKERS: tuple[str, ...] = (
    "先",
    "暂缓",
    "立即",
    "停止",
    "直接",
    "优先",
    "必须",
    "不得",
)

_RECENT_SYNC_MARKERS: tuple[str, ...] = (
    "今日开工同步",
    "今日同步",
    "日常同步",
    "开工同步",
    "今日事项",
)

_SUBSTANTIVE_TOPIC_MARKERS: tuple[str, ...] = (
    "复核",
    "回收",
    "告警",
    "补丁",
    "风险",
    "发布",
    "上线",
    "修复",
    "融资",
    "预算",
    "合同",
    "验收",
    "交付",
    "离职",
    "绩效",
    "考勤",
    "报价",
    "扩容",
    "构建",
    "权限",
)

_PENDING_MARKERS: tuple[str, ...] = (
    "剩余",
    "还有",
    "待",
    "未开票",
    "未回收",
    "未完成",
    "未付",
    "异常",
)

_FINAL_CHANGE_RE = re.compile(
    r"(?:改为|降到|降至|降为|调整为|提升到|优化为|缩短到|压缩到|更新为|变为)\s*$"
)

_GENERIC_SYNC_FRAGMENTS: tuple[str, ...] = (
    "收到，我负责跟进今日事项",
    "已更新进度与风险到共享文档",
    "暂无新增阻塞",
)

_NAME_LABEL_RE = re.compile(
    r"(?:负责人|交接人|验收人|复核人|联系人|接待人|陪同人)\s*[:：]?\s*"
    r"([\u4e00-\u9fffA-Za-z0-9_]{2,20})"
)
_NAME_BY_RE = re.compile(
    r"由\s*([\u4e00-\u9fffA-Za-z0-9_]{2,8})\s*(?:负责|跟进|交接|处理|陪同|接待)"
)
_NAME_ROLE_RE = re.compile(
    r"([\u4e00-\u9fffA-Za-z0-9_]{2,8})(?:负责|陪同|接待)"
)
_AT_RE = re.compile(r"@([\u4e00-\u9fffA-Za-z0-9_]{2,20})")


def wants_concise_answer(question: str) -> bool:
    """判断问题是否明确要求简短答案。"""
    text = str(question or "")
    return any(marker in text for marker in _CONCISE_MARKERS)


def synthesize_answer(
    question: str,
    items: list[dict[str, Any]],
    *,
    max_chars: int = 2000,
    preview_limit: int = 3,
    intro: str = _DEFAULT_INTRO,
) -> str:
    """生成最终回答，兼容只关心文本的调用方。"""
    return synthesize_answer_with_evidence(
        question,
        items,
        max_chars=max_chars,
        preview_limit=preview_limit,
        intro=intro,
    ).answer


def synthesize_answer_with_evidence(
    question: str,
    items: list[dict[str, Any]],
    *,
    max_chars: int = 2000,
    preview_limit: int = 3,
    intro: str = _DEFAULT_INTRO,
) -> SynthesisResult:
    """生成答案并返回实际支撑答案的消息 id，供上游过滤 citations。"""
    kind = _question_kind(str(question or ""))
    result: SynthesisResult | None = None
    if kind == "recent":
        result = _answer_recent(question, items)
    elif kind == "time":
        result = _answer_time(question, items)
    elif kind == "person":
        result = _answer_person(question, items)
    elif kind == "amount":
        result = _answer_amount(question, items)
    elif kind == "boolean":
        result = _answer_boolean(question, items)
    elif kind == "attribute":
        result = _answer_attribute(question, items)
    else:
        result = _answer_generic(question, items)

    if result is None:
        result = _answer_generic(question, items)
    if result is None:
        limit = 1 if wants_concise_answer(str(question or "")) else max(1, int(preview_limit))
        result = _render_preview(question, items, limit, intro)
    result.answer = str(result.answer or "")[: int(max_chars)]
    return result


def _question_kind(question: str) -> str:
    """识别问题类型，时间/人员/金额/布尔优先于一般属性。"""
    text = str(question or "")
    if any(marker in text for marker in _RECENT_MARKERS):
        return "recent"
    if any(marker in text for marker in _TIME_MARKERS):
        return "time"
    if any(marker in text for marker in _PERSON_MARKERS):
        return "person"
    if any(marker in text for marker in _AMOUNT_MARKERS):
        return "amount"
    if any(marker in text for marker in _BOOLEAN_MARKERS):
        return "boolean"
    if any(marker in text for marker in _ATTRIBUTE_MARKERS):
        return "attribute"
    return "generic"


def _answer_time(question: str, items: list[dict[str, Any]]) -> SynthesisResult | None:
    """抽取时间段问题：以最相关证据为准，并识别稍后的作废消息。"""
    ranked = _ranked_items(question, items)
    if not ranked:
        return None
    main = ranked[0]
    matched = _TIME_PHRASE_RE.search(_text_of(main))
    if not matched:
        return None
    when = re.sub(r"\s+", " ", (matched.group("when") or "").strip())
    span = re.sub(r"\s*[-—~至到]\s*", " - ", matched.group("range")).replace("：", ":")
    subject = _subject_of(question) or "该安排"
    answer = f"{subject}时间：{when} {span}。" if when else f"{subject}时间：{span}。"
    cited = [_message_id(main)]
    supersede = _pick_supersede(items, main)
    if supersede is not None:
        sender = str(supersede.get("sender_name") or "").strip()
        when_hint = _time_hint(supersede)
        prefix = f"{sender} {when_hint}".strip()
        answer += f" 但{prefix or '后续消息'}又提示此前安排已作废，具体以飞书日历为准。"
        cited.append(_message_id(supersede))
    return SynthesisResult(answer=answer, cited_item_ids=[item for item in cited if item])


def _answer_person(question: str, items: list[dict[str, Any]]) -> SynthesisResult | None:
    """抽取人员类答案：负责人/承接人/陪同人等。"""
    ranked = _ranked_items(question, items)
    names: list[str] = []
    cited: list[str] = []
    for item in ranked:
        found = _extract_names(_text_of(item))
        if not found:
            continue
        cited.append(_message_id(item))
        for name in found:
            if name not in names:
                names.append(name)
    if not names:
        return None
    subject = _subject_of(question) or "相关人员"
    label = "负责人" if any(
        marker in str(question or "") for marker in ("负责人", "交接人", "验收人", "复核人")
    ) else "相关人员"
    answer = f"{subject}{label}：{'、'.join(names[:8])}。"
    return SynthesisResult(answer=answer, cited_item_ids=[item for item in cited if item])


def _answer_amount(question: str, items: list[dict[str, Any]]) -> SynthesisResult | None:
    """抽取金额/数量类答案。"""
    ranked = _ranked_items(question, items)
    for item in ranked:
        matched = _AMOUNT_VALUE_RE.search(_text_of(item))
        if not matched:
            continue
        subject = _subject_of(question) or "该金额"
        answer = f"{subject}是「{matched.group(0).strip()}」。"
        return SynthesisResult(answer=answer, cited_item_ids=[_message_id(item)])
    return None


def _answer_boolean(question: str, items: list[dict[str, Any]]) -> SynthesisResult | None:
    """布尔类问题优先看最相关证据中是否已有明确结论。"""
    ranked = _ranked_items(question, items)
    if not ranked:
        return None
    text = _text_of(ranked[0])
    if any(marker in text for marker in ("没有", "暂无", "未找到", "未查到", "不存在", "尚未")):
        verdict = "没有。"
    elif any(marker in text for marker in ("有", "是", "已", "确认", "定了")):
        verdict = "是的，已有相关消息或安排。"
    else:
        return None
    subject = _subject_of(question) or "该项"
    return SynthesisResult(
        answer=f"{subject}：{verdict}",
        cited_item_ids=[_message_id(ranked[0])],
    )


def _answer_attribute(question: str, items: list[dict[str, Any]]) -> SynthesisResult | None:
    """属性类问题优先抽「答案」标记，其次给最相关的一句话。"""
    value, item, kind = _find_quoted_value(question, items)
    if value and item is not None and kind:
        subject = _subject_of(question)
        answer = (
            f"{subject}是「{value}」{kind}的。"
            if subject
            else f"是「{value}」{kind}的。"
        )
        return SynthesisResult(answer=answer, cited_item_ids=[_message_id(item)])
    return _sentence_answer(question, items, with_subject=True)


def _answer_generic(question: str, items: list[dict[str, Any]]) -> SynthesisResult | None:
    """通用问题直接返回一句最有信息量的证据结论。"""
    return _sentence_answer(question, items, with_subject=False)


def _sentence_answer(
    question: str,
    items: list[dict[str, Any]],
    *,
    with_subject: bool,
) -> SynthesisResult | None:
    """从最相关证据中选一句回答，避免列出整批消息原文。"""
    ranked = _ranked_items(question, items)
    if not ranked:
        return None
    best = ranked[0]
    sentence = _best_sentence(question, _text_of(best))
    if not sentence:
        return None
    if with_subject:
        subject = _subject_of(question)
        if subject and subject not in sentence:
            sentence = f"{subject}：{sentence}"
    return SynthesisResult(answer=sentence, cited_item_ids=[_message_id(best)])


def _find_quoted_value(
    question: str,
    items: list[dict[str, Any]],
) -> tuple[str, dict[str, Any] | None, str]:
    """从「答案」后接属性词的证据中抽取被引用片段。"""
    kinds = [kind for kind in _KIND_MARKERS if kind in str(question or "")]
    for item in items:
        text = _text_of(item)
        for kind in kinds:
            pattern = re.compile(
                rf'[「“"『](?P<value>[^」”"』]{{1,60}})[」”"』]\s*{re.escape(kind)}'
            )
            matched = pattern.search(text)
            if matched:
                return matched.group("value").strip(), item, kind
    return "", None, ""


def _ranked_items(question: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按问题特征与证据的重合度排序，最终版消息获得额外权重。"""
    q_grams = _feature_grams(question)
    ranked: list[tuple[float, int, dict[str, Any]]] = []
    for idx, item in enumerate(items):
        text = _text_of(item)
        grams = _feature_grams(text)
        overlap = (len(q_grams & grams) / len(q_grams)) if q_grams else 0.0
        for token in q_grams:
            if token in text:
                overlap += 0.05
        if any(marker in text for marker in ("最终版", "最终确认", "确认版", "最终安排")):
            overlap += 0.2
        if _SUPERSEDE_RE.search(text):
            overlap -= 0.05
        ranked.append((overlap, -idx, item))
    ranked.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    return [entry[2] for entry in ranked]


def _best_sentence(question: str, text: str) -> str:
    """在单条证据里挑与问题最相关的一句话。"""
    q_grams = _feature_grams(question)
    parts = [
        part.strip()
        for part in re.split(r"(?<=[。！？!?；;\n])", text)
        if part.strip()
    ]
    if not parts:
        return _trim(text, 120)
    scored: list[tuple[float, int, str]] = []
    for part in parts:
        grams = _feature_grams(part)
        score = len(q_grams & grams) if q_grams else 1.0
        for marker in ("因为", "所以", "结论", "确认", "决定", "最终", "提醒"):
            if marker in part:
                score += 0.5
        if len(part) > 160:
            score -= 0.4
        scored.append((score, -len(part), part))
    scored.sort(reverse=True)
    return _trim(scored[0][2], 120)


def _extract_names(text: str) -> list[str]:
    """提取人名：带标签、由某人负责、姓名后接角色词或 @ 提及。"""
    names: list[str] = []
    for pattern in (_NAME_LABEL_RE, _NAME_BY_RE, _NAME_ROLE_RE, _AT_RE):
        for matched in pattern.finditer(text):
            name = matched.group(1).strip()
            if name and name not in names:
                names.append(name)
    return names


def _pick_supersede(
    items: list[dict[str, Any]],
    main: dict[str, Any],
) -> dict[str, Any] | None:
    """找到晚于主证据且明确作废/取消/以其他安排为准的消息。"""
    main_time = _message_datetime(main)
    candidates: list[dict[str, Any]] = []
    for item in items:
        if _message_id(item) == _message_id(main):
            continue
        if not _SUPERSEDE_RE.search(_text_of(item)):
            continue
        item_time = _message_datetime(item)
        if main_time is None or item_time is None or item_time > main_time:
            candidates.append(item)
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: _message_datetime(item) or datetime.min,
    )
    return candidates[-1]


def _subject_of(question: str) -> str:
    """提取疑问词前后的主体，例如「罗总」「陪罗总吃饭」。"""
    text = str(question or "").strip().rstrip("？?。！! ")
    for marker in _QUESTION_MARKERS:
        if marker not in text:
            continue
        head, _, tail = text.partition(marker)
        candidate = head.strip().strip("的是了吗呢") or tail.strip().strip("的是了吗呢")
        candidate = re.sub(r"^(请|帮我|告诉我|查一下)\s*", "", candidate).strip()
        return candidate
    return ""


def _feature_grams(text: str) -> set[str]:
    """生成 2/3 字窗口特征，用于计算问题与证据的相关度。"""
    cleaned = str(text or "")
    for word in _REMOVE_WORDS:
        cleaned = cleaned.replace(word, " ")
    joined = "".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", cleaned)).lower()
    grams: set[str] = set()
    for size in (2, 3):
        grams.update(joined[i : i + size] for i in range(max(0, len(joined) - size + 1)))
    return grams


def _text_of(item: dict[str, Any]) -> str:
    """证据条目可能只带摘要或整条正文。"""
    return str(item.get("excerpt") or item.get("content") or "").strip()


def _message_id(item: dict[str, Any]) -> str:
    return str(item.get("message_id") or "")


def _message_datetime(item: dict[str, Any]) -> datetime | None:
    """解析 create_time 的常见时间格式，无法解析时返回 None。"""
    raw = str(item.get("create_time") or "").strip()
    if not raw:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
    ):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromtimestamp(float(raw))
    except (ValueError, OverflowError):
        return None


def _time_hint(item: dict[str, Any]) -> str:
    """从 create_time 中提取可用于提示的时分信息。"""
    raw = str(item.get("create_time") or "")
    matched = re.search(r"(\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2})", raw)
    return matched.group(1).replace("T", " ") if matched else ""


def _render_preview(
    question: str,
    items: list[dict[str, Any]],
    limit: int,
    intro: str,
) -> SynthesisResult:
    """仍抽不到答案时的兜底：只渲染少量证据并记录对应消息 id。"""
    lines = [str(intro or _DEFAULT_INTRO)]
    cited: list[str] = []
    rendered = 0
    for item in items:
        if rendered >= limit:
            break
        excerpt = _text_of(item)
        if not excerpt:
            continue
        when = str(item.get("create_time") or "未知时间")
        who = str(item.get("sender_name") or "未知发送者")
        lines.append(f"{rendered + 1}. [{when}] {who}：{_trim(excerpt, 240)}")
        cited.append(_message_id(item))
        rendered += 1
    return SynthesisResult(
        answer="\n".join(lines),
        cited_item_ids=[item for item in cited if item],
    )


def _trim(text: str, limit: int) -> str:
    """按字符截断，并在截断处补省略号。"""
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip("，,。；; ") + "…"
