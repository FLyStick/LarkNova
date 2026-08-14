"""单条 trace 的指标打分与黄金用例运行后的汇总统计。"""

from __future__ import annotations

import statistics
from typing import Any

from feishu_agent.agent.protocol import AgentTrace
from feishu_agent.eval.golden import GoldenCase


def evaluate_case(trace: AgentTrace | dict[str, Any], case: GoldenCase) -> dict[str, Any]:
    """按一个黄金用例评估一次回答，返回结构化评分结果。"""
    tr = _as_trace(trace)
    answer = str(tr.answer or "")
    citation_ids = [str(item.message_id or "") for item in tr.citations]
    # 关键词命中要求期望关键词都在答案中出现。
    keyword_hits = [
        keyword
        for keyword in case.expected_keywords
        if keyword and keyword in answer
    ]
    all_keywords = bool(case.expected_keywords) and len(keyword_hits) == len(
        case.expected_keywords
    )
    reference_set = {str(item) for item in case.reference_ids if str(item).strip()}
    # 引用命中要求回答引用的消息 id 与期望引用有交集。
    has_reference_citation = bool(reference_set & set(citation_ids))

    # 允许拒答的用例以正确拒答为通过条件。
    if case.allow_refused:
        correct = tr.status == "refused"
    else:
        # 普通用例：状态正常，且引用命中或关键词全中之一成立即可。
        correct = bool(
            tr.status == "ok"
            and (has_reference_citation or all_keywords)
        )

    return {
        "case_id": case.id,
        "type": case.type,
        "question": case.question,
        "chat_ids": list(case.chat_ids),
        "expected_keywords": list(case.expected_keywords),
        "reference_ids": list(case.reference_ids),
        "allow_refused": case.allow_refused,
        "status": tr.status,
        "refusal_reason": tr.refusal_reason,
        "answer": answer[:2000],
        "latency_ms": int(tr.latency_ms or 0),
        "tokens": int(tr.tokens or 0),
        "citations": [item.to_dict() for item in tr.citations],
        "citation_ids": citation_ids,
        "keyword_hits": keyword_hits,
        "all_keywords_hit": all_keywords,
        "has_reference_citation": has_reference_citation,
        "correct": correct,
    }


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """汇总整体准确率、拒答表现以及延迟/token 统计。"""
    total = len(results)
    passed = sum(1 for result in results if result.get("correct"))

    # 按 search/summary/recent/graph 等用例类型分别汇总指标。
    by_type: dict[str, dict[str, Any]] = {}
    for result in results:
        bucket = by_type.setdefault(
            str(result.get("type") or "search"),
            {"total": 0, "passed": 0, "accuracy": 0.0, "mean_latency_ms": 0.0},
        )
        bucket["total"] += 1
        if result.get("correct"):
            bucket["passed"] += 1
        bucket.setdefault("latency_ms", []).append(int(result.get("latency_ms") or 0))
    for bucket in by_type.values():
        bucket["accuracy"] = round(
            bucket["passed"] / bucket["total"], 4
        ) if bucket["total"] else 0.0
        bucket["mean_latency_ms"] = round(
            sum(bucket["latency_ms"]) / len(bucket["latency_ms"]), 1
        ) if bucket["latency_ms"] else 0.0
        bucket.pop("latency_ms", None)

    # 只统计正常回答的引用/关键词命中率，异常结果不进入分母。
    ok_results = [result for result in results if result.get("status") == "ok"]
    refusal_cases = [result for result in results if result.get("allow_refused")]
    refusal_passed = sum(
        1 for result in refusal_cases if result.get("status") == "refused"
    )
    citation_rate = (
        round(
            sum(1 for result in ok_results if result.get("has_reference_citation"))
            / len(ok_results),
            4,
        )
        if ok_results
        else None
    )
    keyword_rate = (
        round(
            sum(1 for result in ok_results if result.get("all_keywords_hit"))
            / len(ok_results),
            4,
        )
        if ok_results
        else None
    )
    latencies = [int(result.get("latency_ms") or 0) for result in results]
    tokens = [int(result.get("tokens") or 0) for result in results]

    return {
        "total": total,
        "passed": passed,
        "accuracy": round(passed / total, 4) if total else 0.0,
        "refusal_total": len(refusal_cases),
        "refusal_passed": refusal_passed,
        "refusal_accuracy": (
            round(refusal_passed / len(refusal_cases), 4)
            if refusal_cases
            else None
        ),
        "reference_citation_rate": citation_rate,
        "keyword_hit_rate": keyword_rate,
        "mean_latency_ms": round(statistics.mean(latencies), 1) if latencies else 0.0,
        "median_latency_ms": round(statistics.median(latencies), 1) if latencies else 0.0,
        "p95_latency_ms": _percentile(latencies, 95),
        "max_latency_ms": max(latencies) if latencies else 0,
        "mean_tokens": round(statistics.mean(tokens), 1) if tokens else 0.0,
        "total_tokens": sum(tokens),
        "by_type": by_type,
        "failures": [result for result in results if not result.get("correct")][:20],
    }


def _as_trace(trace: AgentTrace | dict[str, Any]) -> AgentTrace:
    """把 AgentTrace 或字典统一规整为 AgentTrace 对象。"""
    if isinstance(trace, AgentTrace):
        return trace
    if isinstance(trace, dict):
        return AgentTrace.from_dict(trace)
    raise TypeError("trace must be AgentTrace or dict")


def _percentile(values: list[int], pct: int) -> float:
    """按线性位置取百分位，空列表时返回 0。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((pct / 100) * (len(ordered) - 1)))))
    return round(float(ordered[index]), 1)
