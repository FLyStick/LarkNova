from __future__ import annotations

import argparse
import json
import logging
import threading
import time

from feishu_agent.api.server import create_server
from feishu_agent.config import Settings
from feishu_agent.database.db import Database
from feishu_agent.doctor import format_doctor, run_doctor
from feishu_agent.feishu.client import FeishuClient
from feishu_agent.sync.runner import SyncRunner
from feishu_agent.boundary import audit_local_db, prune_local_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("feishu-agent")


def build_runner(settings: Settings, identity: str | None = None) -> SyncRunner:
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
    )


def cmd_sync(args: argparse.Namespace) -> int:
    settings = Settings()
    runner = build_runner(settings, args.identity)
    result = runner.sync_all(chat_ids=args.chat_id, full=args.full)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["errors"] else 0


def cmd_doctor(args: argparse.Namespace) -> int:
    settings = Settings()
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
    settings = Settings()
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
    settings = Settings()
    db = Database(settings.db_path)
    db.init()
    print(json.dumps(db.stats(), indent=2))
    return 0


def cmd_metrics(args: argparse.Namespace) -> int:
    settings = Settings()
    db = Database(settings.db_path)
    db.init()
    print(json.dumps(db.metrics(limit=args.limit), ensure_ascii=False, indent=2))
    return 0


def cmd_normalize(args: argparse.Namespace) -> int:
    settings = Settings()
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


def cmd_serve(args: argparse.Namespace) -> int:
    settings = Settings()
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
    )

    if interval and interval > 0:
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
    while True:
        time.sleep(interval_seconds)
        try:
            result = runner.sync_all()
            logger.info("periodic sync result: %s", json.dumps(result, ensure_ascii=False))
        except Exception:
            logger.exception("periodic sync failed")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Feishu message sync agent")
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

    normalize = sub.add_parser("normalize", help="inspect or rebuild normalized message text")
    normalize.add_argument("--rebuild", action="store_true", help="recompute normalized text/hash for all messages")
    normalize.set_defaults(func=cmd_normalize)

    serve = sub.add_parser("serve", help="start HTTP API with optional periodic sync")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--interval", type=int, default=None, help="sync interval in seconds; 0 disables")
    serve.add_argument("--sync-on-start", action="store_true", help="run an initial sync before serving")
    serve.add_argument("--identity", default=None, help="user or bot")
    serve.set_defaults(func=cmd_serve)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
