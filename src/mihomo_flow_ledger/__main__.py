from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from .client import ControllerConfig, DEFAULT_UNIX_SOCKET, MihomoClient
from .monitor import Sampler
from .process_lookup import lookup_process_name, lsof_path
from .reports import export_csv, export_markdown, format_report
from .store import LedgerStore


DEFAULT_DATABASE = "data/ledger.sqlite"


def add_controller_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--controller",
        default=DEFAULT_UNIX_SOCKET,
        help="Mihomo controller URL or unix socket path",
    )
    parser.add_argument("--secret", default=None, help="Mihomo controller secret")
    parser.add_argument("--timeout", type=float, default=5.0, help="Controller timeout in seconds")


def add_database_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--database", default=DEFAULT_DATABASE, help="SQLite database path")


def build_client(args: argparse.Namespace) -> MihomoClient:
    return MihomoClient(
        ControllerConfig(
            controller=args.controller,
            secret=args.secret,
            timeout=args.timeout,
        )
    )


def command_doctor(args: argparse.Namespace) -> int:
    client = build_client(args)
    try:
        version = client.version()
        raw_connections = client.raw_connections()
        snapshots = client.connection_snapshots(process_lookup=lookup_process_name)
    except Exception as exc:
        print(f"controller: failed ({exc})", file=sys.stderr)
        return 1

    total = len(raw_connections.get("connections") or [])
    known = sum(1 for item in snapshots if item.process != "unknown")
    lsof = lsof_path()

    print(f"controller: ok ({args.controller})")
    print(f"version: {version}")
    print(f"connections: {total}")
    print(f"process attribution: {known}/{total} known")
    print(f"lsof: {lsof or 'not found'}")
    return 0


def command_run(args: argparse.Namespace) -> int:
    client = build_client(args)
    store = LedgerStore(args.database)
    sampler = Sampler(client=client, store=store, interval=args.interval)
    print(f"writing to {Path(args.database)}")
    print(f"polling {args.controller} every {args.interval:g}s")
    try:
        sampler.run_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


def report_date(args: argparse.Namespace) -> str:
    return args.date or datetime.now().astimezone().date().isoformat()


def rows_for(args: argparse.Namespace, store: LedgerStore) -> tuple[str, str, list[dict[str, int | str]]]:
    date = report_date(args)
    if args.by == "host":
        return date, "host", store.daily_host(date, limit=args.limit)
    return date, "process", store.daily_process(date, limit=args.limit)


def command_today(args: argparse.Namespace) -> int:
    store = LedgerStore(args.database)
    date, key, rows = rows_for(args, store)
    title = f"Traffic by {key}"
    print(format_report(date, rows, title=title, key=key))
    return 0


def command_export(args: argparse.Namespace) -> int:
    store = LedgerStore(args.database)
    date, key, rows = rows_for(args, store)
    title = f"Traffic by {key}"
    if args.format == "csv":
        export_csv(args.output, rows, key=key)
    else:
        export_markdown(args.output, date, rows, title=title, key=key)
    print(f"wrote {args.output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mihomo-flow-ledger")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Check controller and attribution state")
    add_controller_args(doctor)
    doctor.set_defaults(func=command_doctor)

    run = subparsers.add_parser("run", help="Poll Mihomo and write byte deltas")
    add_controller_args(run)
    add_database_arg(run)
    run.add_argument("--interval", type=float, default=1.0, help="Poll interval in seconds")
    run.set_defaults(func=command_run)

    today = subparsers.add_parser("today", help="Print daily traffic report")
    add_database_arg(today)
    today.add_argument("--date", default=None, help="Report date, defaults to today")
    today.add_argument("--by", choices=["process", "host"], default="process")
    today.add_argument("--limit", type=int, default=20)
    today.set_defaults(func=command_today)

    export = subparsers.add_parser("export", help="Export a daily traffic report")
    add_database_arg(export)
    export.add_argument("--date", required=True)
    export.add_argument("--by", choices=["process", "host"], default="process")
    export.add_argument("--format", choices=["markdown", "csv"], default="markdown")
    export.add_argument("--output", required=True)
    export.add_argument("--limit", type=int, default=50)
    export.set_defaults(func=command_export)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

