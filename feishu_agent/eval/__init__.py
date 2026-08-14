"""M5 评估模块：基于合成语料的黄金用例回放与指标打分。"""

from feishu_agent.eval.golden import (
    GOLDEN_CASES,
    GoldenCase,
    dump_golden,
    load_golden,
)
from feishu_agent.eval.metrics import evaluate_case, summarize_results
from feishu_agent.eval.report import (
    format_report,
    load_report,
    write_report,
)
from feishu_agent.eval.runner import EvalRunner

__all__ = [
    "EvalRunner",
    "GOLDEN_CASES",
    "GoldenCase",
    "dump_golden",
    "evaluate_case",
    "format_report",
    "load_golden",
    "load_report",
    "summarize_results",
    "write_report",
]
