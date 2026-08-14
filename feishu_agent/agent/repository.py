"""Agent 运行记录持久化：可回放 trace、延迟统计与应用状态。"""

from __future__ import annotations

import json
import math
import sqlite3
from collections import Counter
from typing import Any

from feishu_agent.agent.protocol import AgentStep, AgentTrace, Citation


class AgentRepository:
    """SQLite 仓库：负责 Agent 运行记录与逐步骤 trace 的持久化。"""

    def __init__(self, db: Any) -> None:
        self.db = db

    def record(self, trace: AgentTrace) -> None:
        """写入一次运行及其全部步骤，运行主表与步骤表在同一事务内提交。"""
        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                INSERT INTO agent_runs (
                    trace_id, question, mode, status, answer, refusal_reason,
                    degraded, chat_ids_json, citations_json, tokens, latency_ms,
                    started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace.trace_id,
                    trace.question,
                    trace.mode,
                    trace.status,
                    trace.answer,
                    trace.refusal_reason,
                    1 if trace.degraded else 0,
                    json.dumps(trace.chat_ids, ensure_ascii=False),
                    json.dumps(
                        [item.to_dict() for item in trace.citations],
                        ensure_ascii=False,
                    ),
                    int(trace.tokens or 0),
                    int(trace.latency_ms or 0),
                    trace.created_at,
                    trace.finished_at,
                ),
            )
            run_id = int(cursor.lastrowid)
            for step in trace.steps:
                conn.execute(
                    """
                    INSERT INTO agent_traces (
                        run_id, trace_id, step_seq, step_kind, tool, status,
                        input_json, output_json, error, latency_ms, started_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        trace.trace_id,
                        step.seq,
                        step.kind,
                        step.tool,
                        step.status,
                        json.dumps(step.input, ensure_ascii=False, default=str),
                        json.dumps(step.output, ensure_ascii=False, default=str),
                        step.error,
                        int(step.latency_ms or 0),
                        step.started_at,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def record_from_dict(self, data: dict[str, Any]) -> None:
        """从字典形式的 trace 恢复对象后写入数据库。"""
        self.record(AgentTrace.from_dict(data))

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        """按时间倒序列出最近运行记录，默认不返回详细步骤以控制体积。"""
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM agent_runs
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 200)),),
            ).fetchall()
            runs = [self._decode_run(row) for row in rows]
            for run in runs:
                run.pop("steps", None)
            return runs
        finally:
            conn.close()

    def get(self, run_id: str) -> dict[str, Any] | None:
        """按 trace_id 或数据库自增 id 查询单次运行及其完整步骤。"""
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT * FROM agent_runs
                WHERE trace_id = ? OR CAST(id AS TEXT) = ?
                ORDER BY id DESC LIMIT 1
                """,
                (str(run_id), str(run_id)),
            ).fetchone()
            if row is None:
                return None
            run = self._decode_run(row)
            traces = [
                dict(step)
                for step in conn.execute(
                    """
                    SELECT step_seq, step_kind, tool, status, input_json,
                           output_json, error, latency_ms, started_at
                    FROM agent_traces
                    WHERE run_id = ?
                    ORDER BY step_seq
                    """,
                    (int(row["id"]),),
                )
            ]
            run["steps"] = [
                {
                    **step,
                    "seq": int(step["step_seq"]),
                    "kind": step.pop("step_kind"),
                    "input": self._decode_json(step.pop("input_json")),
                    "output": self._decode_json(step.pop("output_json")),
                }
                for step in traces
            ]
            return run
        finally:
            conn.close()

    def stats(self) -> dict[str, Any]:
        """统计运行总量、状态/模式分布、token、引用数和延迟分位数。"""
        conn = self._connect()
        try:
            total = int(
                conn.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0]
            )
            status_counts = {
                str(row["status"]): int(row["c"])
                for row in conn.execute(
                    """
                    SELECT status, COUNT(*) AS c
                    FROM agent_runs
                    GROUP BY status
                    ORDER BY status
                    """
                )
            }
            modes = {
                str(row["mode"]): int(row["c"])
                for row in conn.execute(
                    """
                    SELECT mode, COUNT(*) AS c
                    FROM agent_runs
                    GROUP BY mode
                    ORDER BY mode
                    """
                )
            }
            latencies = sorted(
                int(row[0])
                for row in conn.execute(
                    "SELECT latency_ms FROM agent_runs WHERE latency_ms >= 0"
                )
            )
            tokens = int(
                conn.execute(
                    "SELECT COALESCE(SUM(tokens), 0) FROM agent_runs"
                ).fetchone()[0]
            )
            citations = 0
            for row in conn.execute("SELECT citations_json FROM agent_runs"):
                data = self._decode_json(row[0])
                if isinstance(data, list):
                    citations += sum(
                        1 for item in data if isinstance(item, dict)
                    )
            return {
                "runs_total": total,
                "status": status_counts,
                "modes": modes,
                "tokens": tokens,
                "citations": citations,
                "latency_ms": {
                    "avg": round(sum(latencies) / len(latencies), 2)
                    if latencies
                    else None,
                    "p50": _percentile(latencies, 50) if latencies else None,
                    "p95": _percentile(latencies, 95) if latencies else None,
                    "max": latencies[-1] if latencies else None,
                },
            }
        finally:
            conn.close()

    def _decode_run(self, row: sqlite3.Row) -> dict[str, Any]:
        """把数据库行转成运行字典，并反序列化 JSON 字段。"""
        run = dict(row)
        run["chat_ids"] = self._decode_json(run.pop("chat_ids_json")) or []
        run["citations"] = [
            item.to_dict()
            for item in (
                Citation.from_dict(item)
                for item in (self._decode_json(run.pop("citations_json")) or [])
                if isinstance(item, dict)
            )
        ]
        run["degraded"] = bool(run.get("degraded"))
        return run

    @staticmethod
    def _decode_json(raw: str | None) -> Any:
        """安全解析 JSON 字段，坏数据返回 None 而不是中断查询。"""
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    def _connect(self) -> sqlite3.Connection:
        """打开数据库连接并启用行字典与外键约束。"""
        conn = sqlite3.connect(self.db.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


def _percentile(values: list[int], percentile: float) -> int:
    """线性插值计算延迟分位数，空列表返回 0。"""
    if not values:
        return 0
    values = sorted(values)
    rank = (len(values) - 1) * percentile / 100.0
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return int(values[int(rank)])
    return int(values[lower] + (values[upper] - values[lower]) * (rank - lower))
