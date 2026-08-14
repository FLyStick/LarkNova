"""Persistent M5 resume metrics report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from feishu_agent.config import PROJECT_ROOT

DEFAULT_REPORT_PATH = PROJECT_ROOT / "data" / "reports" / "resume_metrics.json"


def write_report(report: dict[str, Any], path: str | Path | None = None) -> str:
    target = _report_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(target)


def load_report(path: str | Path | None = None) -> dict[str, Any] | None:
    target = _report_path(path)
    if not target.exists():
        return None
    return json.loads(target.read_text(encoding="utf-8"))


def format_report(report: dict[str, Any]) -> str:
    metrics = report.get("metrics") or {}
    mode = str(report.get("mode") or "-")
    run_at = str(report.get("run_at") or "-")
    total = int(metrics.get("total") or report.get("total") or 0)
    passed = int(metrics.get("passed") or report.get("passed") or 0)
    accuracy = float(metrics.get("accuracy") or 0.0)
    lines = [
        f"M5 评估报告（mode={mode}, run_at={run_at}）",
        f"总准确率：{accuracy:.2%}（{passed}/{total}）",
    ]
    if metrics.get("refusal_total"):
        lines.append(
            "拒答准确率：{:.2%}（{}/{})".format(
                float(metrics.get("refusal_accuracy") or 0.0),
                int(metrics.get("refusal_passed") or 0),
                int(metrics.get("refusal_total") or 0),
            )
        )
    for key, label in (
        ("reference_citation_rate", "引用命中率"),
        ("keyword_hit_rate", "关键词命中率"),
    ):
        value = metrics.get(key)
        if value is not None:
            lines.append(f"{label}：{float(value):.2%}")
    if metrics.get("mean_latency_ms") is not None:
        lines.append(
            "延迟：mean {}ms / p95 {}ms / max {}ms".format(
                float(metrics.get("mean_latency_ms") or 0.0),
                float(metrics.get("p95_latency_ms") or 0.0),
                int(metrics.get("max_latency_ms") or 0),
            )
        )
    if metrics.get("total_tokens") is not None:
        lines.append(
            "Token：总计 {}，平均 {}".format(
                int(metrics.get("total_tokens") or 0),
                float(metrics.get("mean_tokens") or 0.0),
            )
        )
    by_type = metrics.get("by_type") or {}
    if by_type:
        lines.append("按类型：")
        for case_type, bucket in sorted(by_type.items()):
            lines.append(
                "  {}：{:.2%}（{}/{})".format(
                    case_type,
                    float(bucket.get("accuracy") or 0.0),
                    int(bucket.get("passed") or 0),
                    int(bucket.get("total") or 0),
                )
            )
    failures = metrics.get("failures") or []
    if failures:
        lines.append(f"失败样例 {len(failures)} 个：")
        for failure in failures[:10]:
            lines.append(
                "  {} [{}, status={}]".format(
                    failure.get("case_id"),
                    failure.get("type"),
                    failure.get("status"),
                )
            )
    return "\n".join(lines)


def _report_path(path: str | Path | None) -> Path:
    return Path(path) if path else DEFAULT_REPORT_PATH
