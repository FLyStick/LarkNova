"""CLI 入口：同步、体检、边界清理、统计、Agent、检索、摘要与 HTTP 服务。"""

from __future__ import annotations

import argparse
import json
import logging
import threading
import time
from pathlib import Path

from feishu_agent.api.server import create_server
from feishu_agent.agent import AgentHarness
from feishu_agent.agent.repository import AgentRepository
from feishu_agent.config import Settings
from feishu_agent.database.db import Database
from feishu_agent.doctor import format_doctor, run_doctor
from feishu_agent.eval import EvalRunner, load_golden
from feishu_agent.eval.report import (
    DEFAULT_REPORT_PATH,
    format_report,
    load_report,
    write_report,
)
from feishu_agent.feishu.client import FeishuClient
from feishu_agent.index.repository import IndexRepository
from feishu_agent.summary.repository import SummaryRepository
from feishu_agent.sync.runner import SyncRunner
from feishu_agent.synthetic import seed_database, synthetic_status
from feishu_agent.boundary import audit_local_db, prune_local_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("feishu-agent")


def settings_for_db(args: argparse.Namespace) -> Settings:
    """读取配置，并支持用命令行 --db 覆盖数据库路径。"""
    settings = Settings()
    db = getattr(args, "db", None)
    if db:
        settings.db_path = Path(db)
    return settings


def build_runner(settings: Settings, identity: str | None = None) -> SyncRunner:
    """组装同步执行器：创建飞书客户端、初始化数据库并注入摘要工厂。"""
    client = FeishuClient(
        node=settings.node,
        cli_js=settings.lark_cli_js,
        identity=identity or settings.identity,
        timeout=settings.sync_timeout,
    )
    db = Database(settings.db_path)
    db.init()
    return SyncRunner(
        client,
        db,
        identity=identity or settings.identity,
        allowed_chat_ids=settings.allowed_chat_ids,
        allow_external=settings.allow_external_chats,
        summary_factory=make_summary_factory(settings),
    )


def make_summary_factory(settings: Settings):
    """返回摘要仓库工厂，每次调用创建独立的数据库连接。"""
    def factory() -> SummaryRepository:
        db = Database(settings.db_path)
        db.init()
        return SummaryRepository(db, settings)
    return factory


def make_agent_factory(settings: Settings):
    """返回 Agent 执行器工厂，每次调用创建独立的数据库连接。"""
    def factory() -> AgentHarness:
        return AgentHarness(
            lambda: Database(settings.db_path),
            settings=settings,
        )

    return factory


def cmd_sync(args: argparse.Namespace) -> int:
    """执行一轮同步并输出统计，有错误时返回非零退出码。"""
    settings = settings_for_db(args)
    runner = build_runner(settings, args.identity)
    result = runner.sync_all(chat_ids=args.chat_id, full=args.full)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["errors"] else 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """运行环境自检并输出文本或 JSON 形式的体检报告。"""
    settings = settings_for_db(args)
    client = FeishuClient(
        node=settings.node,
        cli_js=settings.lark_cli_js,
        identity=args.identity or settings.identity,
        timeout=settings.sync_timeout,
    )
    result = run_doctor(
        client,
        identity=args.identity,
        allowed_chat_ids=settings.allowed_chat_ids,
        allow_external=settings.allow_external_chats,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_doctor(result))
    return 0 if result["ok"] else 2



def cmd_boundary(args: argparse.Namespace) -> int:
    """审计本地库中的越界群聊，--prune 时在确认后执行删除。"""
    settings = settings_for_db(args)
    db = Database(settings.db_path)
    db.init()
    audit = audit_local_db(db, settings.allowed_chat_ids, settings.allow_external_chats)
    if args.prune and not args.yes:
        audit["require_yes"] = True
        print(json.dumps(audit, ensure_ascii=False, indent=2))
        return 2
    if args.prune:
        removed = prune_local_db(
            db,
            [item["chat_id"] for item in audit["chats_to_remove"]],
        )
        audit["removed"] = removed
        print(json.dumps(audit, ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0
def cmd_stats(args: argparse.Namespace) -> int:
    """输出本地数据库基础统计。"""
    settings = settings_for_db(args)
    db = Database(settings.db_path)
    db.init()
    print(json.dumps(db.stats(), indent=2))
    return 0


def cmd_metrics(args: argparse.Namespace) -> int:
    """输出近期同步指标与最近运行批次。"""
    settings = settings_for_db(args)
    db = Database(settings.db_path)
    db.init()
    print(json.dumps(db.metrics(limit=args.limit), ensure_ascii=False, indent=2))
    return 0


def cmd_agent(args: argparse.Namespace) -> int:
    """Agent 子命令分发：ask/runs/trace/stats。"""
    settings = settings_for_db(args)
    db = Database(settings.db_path)
    db.init()
    command = args.agent_command
    if command == "ask":
        trace = AgentHarness(
            lambda: Database(settings.db_path),
            settings=settings,
        ).ask(
            args.question,
            mode=args.mode,
            chat_ids=args.chat_id,
        )
        print(json.dumps(trace.to_dict(), ensure_ascii=False, indent=2))
        return 0
    repo = AgentRepository(db)
    if command == "runs":
        runs = repo.list_runs(limit=args.limit)
        print(
            json.dumps(
                {"count": len(runs), "runs": runs},
                ensure_ascii=False,
                indent=2,
            )
        )
    elif command == "trace":
        run = repo.get(args.run_id)
        if run is None:
            print(
                json.dumps(
                    {"ok": False, "error": "run_not_found"},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1
        print(json.dumps({"ok": True, "run": run}, ensure_ascii=False, indent=2))
    elif command == "stats":
        print(json.dumps(repo.stats(), ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"error": f"unknown agent command {command}"}))
        return 1
    return 0


def cmd_normalize(args: argparse.Namespace) -> int:
    """查看或重建消息标准化结果，rebuild 会按当前版本重算全部消息。"""
    settings = settings_for_db(args)
    db = Database(settings.db_path)
    db.init()
    if args.rebuild:
        result = db.rebuild_normalization()
    else:
        stats = db.stats()
        result = {
            "messages": stats["messages"],
            "normalized": stats["normalized"],
            "normalize_errors": stats["normalize_errors"],
            "hint": "使用 --rebuild 按当前 normalize_version 重算全部消息",
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    """索引子命令分发：rebuild/incremental/status/consistency。"""
    settings = settings_for_db(args)
    db = Database(settings.db_path)
    db.init()
    repo = IndexRepository(db)
    command = args.index_command
    if command == "rebuild":
        result = repo.rebuild(
            allow_external=args.allow_external,
            chat_ids=args.chat_id,
            allowed_chat_ids=settings.allowed_chat_ids,
        )
    elif command == "incremental":
        result = repo.incremental(
            chat_ids=args.chat_id,
            allowed_chat_ids=settings.allowed_chat_ids,
        )
    elif command == "status":
        result = repo.status()
    elif command == "consistency":
        result = repo.consistency(
            allow_external=args.allow_external,
            chat_ids=args.chat_id,
            allowed_chat_ids=settings.allowed_chat_ids,
        )
    else:
        result = {"error": f"unknown index command {command}"}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("errors"):
        return 1
    if command == "consistency" and not result.get("consistent"):
        return 2
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    """执行混合检索并输出结果列表。"""
    settings = settings_for_db(args)
    db = Database(settings.db_path)
    db.init()
    result = IndexRepository(db).search(
        args.query,
        chat_ids=args.chat_id,
        limit=args.limit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_graph(args: argparse.Namespace) -> int:
    """知识图谱子命令分发：stats/entity。"""
    settings = settings_for_db(args)
    db = Database(settings.db_path)
    db.init()
    repo = IndexRepository(db)
    if args.graph_command == "stats":
        result = repo.entity_stats()
    else:
        result = repo.query_graph(args.entity)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    """摘要子命令分发：rebuild/incremental/list/get/consistency/status。"""
    settings = settings_for_db(args)
    db = Database(settings.db_path)
    db.init()
    repo = SummaryRepository(db, settings)
    command = args.summary_command
    if command == "rebuild":
        result = repo.rebuild(
            chat_ids=args.chat_id,
            allowed_chat_ids=settings.allowed_chat_ids,
            include_external=args.allow_external,
            mode=args.mode,
        )
    elif command == "incremental":
        result = repo.incremental(
            chat_ids=args.chat_id,
            allowed_chat_ids=settings.allowed_chat_ids,
            mode=args.mode,
        )
    elif command == "list":
        items = repo.list_summaries(
            chat_ids=args.chat_id,
            period_start=args.period_start,
            period_end=args.period_end,
            limit=args.limit,
        )
        result = {"count": len(items), "summaries": items}
    elif command == "get":
        item = repo.get(
            args.chat_id,
            period_start=args.period_start,
            period_end=args.period_end,
        )
        result = {"found": item is not None, "summary": item}
    elif command == "consistency":
        result = repo.consistency(
            chat_ids=args.chat_id,
            allowed_chat_ids=settings.allowed_chat_ids,
            include_external=args.allow_external,
        )
    else:
        result = repo.status()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("errors"):
        return 1
    if command == "consistency" and not result.get("consistent"):
        return 2
    return 0


def cmd_synthetic(args: argparse.Namespace) -> int:
    """合成语料子命令分发：seed/status。"""
    settings = settings_for_db(args)
    db = Database(settings.db_path)
    db.init()
    if args.synthetic_command == "seed":
        result = seed_database(
            db,
            limit=args.messages,
            reset_derived=args.reset_derived,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    status = synthetic_status(db)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0 if status.get("ready") else 2


def cmd_eval(args: argparse.Namespace) -> int:
    """评估子命令分发：run/report/samples。"""
    settings = settings_for_db(args)
    db = Database(settings.db_path)
    db.init()
    if args.eval_command == "run":
        cases = load_golden(args.golden) if args.golden else None
        report = EvalRunner(lambda: Database(settings.db_path), settings).run(
            limit=args.limit,
            mode=args.mode,
            cases=cases,
        )
        path = write_report(report, args.report)
        print(format_report(report))
        print(
            json.dumps(
                {
                    "ok": True,
                    "report_path": path,
                    "synthetic": True,
                    "mode": report["mode"],
                    "total": report["total"],
                    "passed": report["passed"],
                    "accuracy": report["accuracy"],
                    "run_at": report["run_at"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.eval_command == "report":
        report = load_report(args.report)
        if report is None:
            print(json.dumps({"ok": False, "error": "report_not_found"}))
            return 1
        print(format_report(report))
        return 0
    cases = load_golden(args.golden) if args.golden else load_golden()
    if args.limit:
        cases = cases[: args.limit]
    print(
        json.dumps(
            [case.to_dict() for case in cases],
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """启动 HTTP 服务，可按配置开启启动前同步与周期同步。"""
    settings = settings_for_db(args)
    runner = build_runner(settings, args.identity)
    if args.sync_on_start:
        result = runner.sync_all()
        logger.info("initial sync result: %s", json.dumps(result, ensure_ascii=False))

    host = args.host or settings.host
    port = args.port or settings.port
    interval = args.interval if args.interval is not None else settings.sync_interval
    server = create_server(
        (host, port),
        runner,
        lambda: Database(settings.db_path),
        summary_factory=make_summary_factory(settings),
        agent_factory=make_agent_factory(settings),
        api_token=settings.api_token,
        rate_limit_per_min=settings.api_rate_limit_per_min,
    )

    if interval and interval > 0:
        # 周期同步放在后台守护线程，不阻塞 HTTP 主循环。
        thread = threading.Thread(
            target=_periodic_sync,
            args=(runner, interval),
            daemon=True,
            name="periodic-sync",
        )
        thread.start()
        logger.info("periodic sync enabled every %s seconds", interval)

    url = f"http://{host}:{port}"
    logger.info("feishu-agent listening on %s", url)
    print(f"feishu-agent listening on {url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def _periodic_sync(runner: SyncRunner, interval_seconds: int) -> None:
    """后台循环：按固定间隔执行同步，异常仅记录日志不退出线程。"""
    while True:
        time.sleep(interval_seconds)
        try:
            result = runner.sync_all()
            logger.info("periodic sync result: %s", json.dumps(result, ensure_ascii=False))
        except Exception:
            logger.exception("periodic sync failed")


def build_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数树：顶层数据库覆盖参数和全部子命令。"""
    parser = argparse.ArgumentParser(description="Feishu message sync agent")
    parser.add_argument(
        "--db",
        default=None,
        help="override FEISHU_AGENT_DB (pass before the subcommand)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="run one sync pass")
    sync.add_argument("--chat-id", action="append", help="only sync this chat_id; repeatable")
    sync.add_argument("--full", action="store_true", help="ignore stored cursor and fetch everything")
    sync.add_argument("--identity", default=None, help="user or bot")
    sync.set_defaults(func=cmd_sync)

    doctor = sub.add_parser("doctor", help="check bot permissions and data boundary")
    doctor.add_argument("--identity", default=None, help="user or bot")
    doctor.add_argument("--json", action="store_true", help="output JSON only")
    doctor.set_defaults(func=cmd_doctor)
    boundary = sub.add_parser("boundary", help="audit local chats against whitelist/external policy")
    boundary.add_argument("--prune", action="store_true", help="remove chats outside the boundary")
    boundary.add_argument("--yes", action="store_true", help="confirm destructive prune")
    boundary.set_defaults(func=cmd_boundary)

    stats = sub.add_parser("stats", help="show local database counts")
    stats.set_defaults(func=cmd_stats)

    metrics = sub.add_parser("metrics", help="show sync metrics and recent runs")
    metrics.add_argument("--limit", type=int, default=10, help="recent sync runs")
    metrics.set_defaults(func=cmd_metrics)

    agent = sub.add_parser("agent", help="M4 agent ask/runs/trace/stats")
    agent_sub = agent.add_subparsers(dest="agent_command", required=True)

    agent_ask = agent_sub.add_parser("ask", help="answer one question")
    agent_ask.add_argument("question", help="question text")
    agent_ask.add_argument(
        "--mode",
        choices=["auto", "rule", "llm"],
        default="auto",
        help="auto/rule/llm; auto falls back to rule",
    )
    agent_ask.add_argument(
        "--chat-id",
        action="append",
        help="limit to this chat_id; repeatable",
    )
    agent_ask.set_defaults(func=cmd_agent)

    agent_runs = agent_sub.add_parser("runs", help="list recent agent runs")
    agent_runs.add_argument("--limit", type=int, default=20)
    agent_runs.set_defaults(func=cmd_agent)

    agent_trace = agent_sub.add_parser("trace", help="show one trace with steps")
    agent_trace.add_argument("run_id", help="trace_id or numeric run id")
    agent_trace.set_defaults(func=cmd_agent)

    agent_stats = agent_sub.add_parser("stats", help="show agent run statistics")
    agent_stats.set_defaults(func=cmd_agent)

    normalize = sub.add_parser("normalize", help="inspect or rebuild normalized message text")
    normalize.add_argument("--rebuild", action="store_true", help="recompute normalized text/hash for all messages")
    normalize.set_defaults(func=cmd_normalize)

    index = sub.add_parser("index", help="topic index rebuild/incremental/status/consistency")
    index_sub = index.add_subparsers(dest="index_command", required=True)

    index_rebuild = index_sub.add_parser("rebuild", help="rebuild chunks, FTS5, vectors and graph")
    index_rebuild.add_argument("--allow-external", action="store_true", help="include external chats")
    index_rebuild.add_argument("--chat-id", action="append", help="only index this chat_id; repeatable")
    index_rebuild.set_defaults(func=cmd_index)

    index_incremental = index_sub.add_parser("incremental", help="index chats changed since last run")
    index_incremental.add_argument("--chat-id", action="append", help="only check this chat_id; repeatable")
    index_incremental.set_defaults(func=cmd_index)

    index_status = index_sub.add_parser("status", help="show index status and counts")
    index_status.set_defaults(func=cmd_index)

    index_consistency = index_sub.add_parser("consistency", help="verify index matches source messages")
    index_consistency.add_argument("--allow-external", action="store_true", help="include external chats")
    index_consistency.add_argument("--chat-id", action="append", help="only check this chat_id; repeatable")
    index_consistency.set_defaults(func=cmd_index)

    search = sub.add_parser("search", help="hybrid BM25 + sparse TF-IDF search")
    search.add_argument("query", help="query text")
    search.add_argument("--chat-id", action="append", help="limit to this chat_id; repeatable")
    search.add_argument("--limit", type=int, default=10, help="max results")
    search.set_defaults(func=cmd_search)

    graph = sub.add_parser("graph", help="knowledge graph stats and entity queries")
    graph_sub = graph.add_subparsers(dest="graph_command", required=True)
    graph_stats = graph_sub.add_parser("stats", help="entity/edge aggregate counts")
    graph_stats.set_defaults(func=cmd_graph)
    graph_entity = graph_sub.add_parser("entity", help="query an entity by keyword or entity_id")
    graph_entity.add_argument("entity", help="entity value keyword or 64-char entity_id")
    graph_entity.set_defaults(func=cmd_graph)

    summary = sub.add_parser("summary", help="structured AI summaries")
    summary_sub = summary.add_subparsers(dest="summary_command", required=True)

    summary_rebuild = summary_sub.add_parser("rebuild", help="rebuild rolling summaries per chat")
    summary_rebuild.add_argument("--mode", default="rule", help="rule or llm")
    summary_rebuild.add_argument("--allow-external", action="store_true", help="include external chats")
    summary_rebuild.add_argument("--chat-id", action="append", help="only summarize this chat_id; repeatable")
    summary_rebuild.set_defaults(func=cmd_summary)

    summary_incremental = summary_sub.add_parser("incremental", help="refresh summaries after index changes")
    summary_incremental.add_argument("--mode", default="rule", help="rule or llm")
    summary_incremental.add_argument("--chat-id", action="append", help="only check this chat_id; repeatable")
    summary_incremental.set_defaults(func=cmd_summary)

    summary_list = summary_sub.add_parser("list", help="list stored summaries")
    summary_list.add_argument("--chat-id", action="append", help="limit to this chat_id; repeatable")
    summary_list.add_argument("--period-start", default=None, help="period_start >= value")
    summary_list.add_argument("--period-end", default=None, help="period_end <= value")
    summary_list.add_argument("--limit", type=int, default=50, help="max summaries")
    summary_list.set_defaults(func=cmd_summary)

    summary_get = summary_sub.add_parser("get", help="get the latest summary for one chat")
    summary_get.add_argument("--chat-id", required=True)
    summary_get.add_argument("--period-start", default=None)
    summary_get.add_argument("--period-end", default=None)
    summary_get.set_defaults(func=cmd_summary)

    summary_consistency = summary_sub.add_parser("consistency", help="verify summaries match indexed messages")
    summary_consistency.add_argument("--allow-external", action="store_true", help="include external chats")
    summary_consistency.add_argument("--chat-id", action="append", help="only check this chat_id; repeatable")
    summary_consistency.set_defaults(func=cmd_summary)

    status_parser = summary_sub.add_parser("status", help="show summary status and counts")
    status_parser.set_defaults(func=cmd_summary)

    synthetic = sub.add_parser("synthetic", help="M5 deterministic synthetic corpus")
    synthetic_sub = synthetic.add_subparsers(dest="synthetic_command", required=True)

    synthetic_seed = synthetic_sub.add_parser(
        "seed", help="seed chats/messages and rebuild derived layers"
    )
    synthetic_seed.add_argument(
        "--messages",
        type=int,
        default=0,
        help="max messages to seed; 0 = full corpus",
    )
    synthetic_seed.add_argument(
        "--reset-derived",
        dest="reset_derived",
        action="store_true",
        default=True,
        help="rebuild index and summaries after seeding (default)",
    )
    synthetic_seed.add_argument(
        "--no-reset-derived",
        dest="reset_derived",
        action="store_false",
        help="seed fact-source rows only",
    )
    synthetic_seed.set_defaults(func=cmd_synthetic)

    synthetic_status = synthetic_sub.add_parser(
        "status", help="verify synthetic corpus readiness"
    )
    synthetic_status.set_defaults(func=cmd_synthetic)

    eval = sub.add_parser("eval", help="M5 golden evaluation")
    eval_sub = eval.add_subparsers(dest="eval_command", required=True)

    eval_run = eval_sub.add_parser("run", help="run golden cases and write report")
    eval_run.add_argument(
        "--mode",
        choices=["rule", "auto", "llm"],
        default="rule",
        help="agent mode; rule is the deterministic baseline",
    )
    eval_run.add_argument(
        "--limit",
        type=int,
        default=0,
        help="max cases; 0 = all golden cases",
    )
    eval_run.add_argument(
        "--golden",
        default=None,
        help="json golden cases file",
    )
    eval_run.add_argument(
        "--report",
        default=None,
        help="report json path",
    )
    eval_run.set_defaults(func=cmd_eval)

    eval_report = eval_sub.add_parser("report", help="print the latest report")
    eval_report.add_argument(
        "--report",
        default=None,
        help="report json path",
    )
    eval_report.set_defaults(func=cmd_eval)

    eval_samples = eval_sub.add_parser("samples", help="print golden case samples")
    eval_samples.add_argument("--limit", type=int, default=10)
    eval_samples.add_argument(
        "--golden",
        default=None,
        help="json golden cases file",
    )
    eval_samples.set_defaults(func=cmd_eval)

    serve = sub.add_parser("serve", help="start HTTP API with optional periodic sync")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--interval", type=int, default=None, help="sync interval in seconds; 0 disables")
    serve.add_argument("--sync-on-start", action="store_true", help="run an initial sync before serving")
    serve.add_argument("--identity", default=None, help="user or bot")
    serve.set_defaults(func=cmd_serve)

    return parser


def main() -> int:
    """CLI 入口：解析参数后调用对应子命令函数。"""
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
