from __future__ import annotations

import argparse
import json
import logging
import threading
import time

from feishu_agent.api.server import create_server
from feishu_agent.config import Settings
from feishu_agent.database.db import Database
from feishu_agent.feishu.client import FeishuClient
from feishu_agent.sync.runner import SyncRunner

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
    return SyncRunner(client, db, identity=identity or settings.identity)


def cmd_sync(args: argparse.Namespace) -> int:
    settings = Settings()
    runner = build_runner(settings, args.identity)
    result = runner.sync_all(chat_ids=args.chat_id, full=args.full)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["errors"] else 0


def cmd_stats(args: argparse.Namespace) -> int:
    settings = Settings()
    db = Database(settings.db_path)
    db.init()
    print(json.dumps(db.stats(), indent=2))
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

    stats = sub.add_parser("stats", help="show local database counts")
    stats.set_defaults(func=cmd_stats)

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
