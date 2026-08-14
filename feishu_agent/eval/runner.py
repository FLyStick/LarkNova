"""Run the built-in golden set through AgentHarness and score it."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from feishu_agent.agent import AgentHarness
from feishu_agent.config import Settings
from feishu_agent.eval.golden import GOLDEN_CASES, GoldenCase
from feishu_agent.eval.metrics import evaluate_case, summarize_results


class EvalRunner:
    """Deterministic M5 evaluation over a database factory."""

    def __init__(
        self,
        db_factory: Callable[[], Any],
        settings: Settings | None = None,
    ) -> None:
        self.db_factory = db_factory
        self.settings = settings or Settings()

    def run(
        self,
        limit: int | None = None,
        mode: str = "rule",
        cases: list[GoldenCase] | tuple[GoldenCase, ...] | None = None,
    ) -> dict[str, Any]:
        selected = list(cases if cases is not None else GOLDEN_CASES)
        if limit:
            selected = selected[: int(limit)]
        harness = AgentHarness(self.db_factory, self.settings)
        results: list[dict[str, Any]] = []
        for case in selected:
            try:
                trace = harness.ask(
                    case.question,
                    mode=mode,
                    chat_ids=case.chat_ids,
                )
                results.append(evaluate_case(trace, case))
            except Exception as exc:
                results.append(_exception_result(case, exc))

        metrics = summarize_results(results)
        return {
            "synthetic": True,
            "mode": str(mode),
            "run_at": _now_iso(),
            "total": metrics["total"],
            "passed": metrics["passed"],
            "accuracy": metrics["accuracy"],
            "metrics": metrics,
            "cases": results,
        }


def _exception_result(case: GoldenCase, exc: Exception) -> dict[str, Any]:
    return {
        "case_id": case.id,
        "type": case.type,
        "question": case.question,
        "chat_ids": list(case.chat_ids),
        "expected_keywords": list(case.expected_keywords),
        "reference_ids": list(case.reference_ids),
        "allow_refused": case.allow_refused,
        "status": "error",
        "refusal_reason": "eval_exception",
        "answer": "",
        "latency_ms": 0,
        "tokens": 0,
        "citations": [],
        "citation_ids": [],
        "keyword_hits": [],
        "all_keywords_hit": False,
        "has_reference_citation": False,
        "correct": False,
        "error": str(exc),
    }


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
