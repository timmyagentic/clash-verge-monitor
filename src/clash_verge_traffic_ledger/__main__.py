from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from .anomalies import detect_anomalies, format_anomalies
from .client import ControllerConfig, DEFAULT_UNIX_SOCKET, MihomoClient
from .monitor import Sampler
from .process_lookup import lookup_process_name, lsof_path
from .reports import export_csv, export_markdown, format_report
from .service import (
    DEFAULT_LABEL,
    bootout_service,
    bootstrap_service,
    build_launchd_plist,
    default_plist_path,
    write_launchd_plist,
)
from .status import build_status, format_status
from .store import LedgerStore
from .web import serve_dashboard


DEFAULT_DATABASE = "data/ledger.sqlite"
DEFAULT_ANOMALY_BYTE_THRESHOLD = 500 * 1024 * 1024


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


def absolute_path(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


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


def command_status(args: argparse.Namespace) -> int:
    store = LedgerStore(args.database)
    date = report_date(args)
    service_label = None if args.no_service_check else args.service_label
    print(format_status(build_status(store, date, service_label=service_label), date))
    return 0


def command_anomalies(args: argparse.Namespace) -> int:
    store = LedgerStore(args.database)
    date = report_date(args)
    anomalies = detect_anomalies(
        store,
        date,
        byte_threshold=args.byte_threshold,
        unknown_ratio_threshold=args.unknown_ratio_threshold,
        spike_multiplier=args.spike_multiplier,
    )
    print(format_anomalies(anomalies, date))
    return 0


def command_web(args: argparse.Namespace) -> int:
    store = LedgerStore(args.database)
    print(f"serving http://{args.host}:{args.port}/")
    serve_dashboard(store, args.host, args.port)
    return 0


def command_prune(args: argparse.Namespace) -> int:
    store = LedgerStore(args.database)
    count = store.raw_delta_count_before(args.before)
    if args.dry_run:
        print(f"would delete {count} raw delta rows before {args.before}")
        return 0
    deleted = store.delete_raw_before(args.before)
    print(f"deleted {deleted} raw delta rows before {args.before}")
    return 0


def command_compact(args: argparse.Namespace) -> int:
    store = LedgerStore(args.database)
    count = store.raw_delta_count_before(args.before)
    if args.dry_run:
        print(f"would compact {count} raw delta rows before {args.before}")
        return 0
    result = store.compact_raw_before(args.before)
    print(
        "compacted {deleted} raw delta rows before {before}; "
        "{remaining} raw rows remain; {dates} rollup dates preserved".format(
            deleted=result["deleted_raw_rows"],
            before=args.before,
            remaining=result["remaining_raw_rows"],
            dates=result["preserved_rollup_dates"],
        )
    )
    return 0


def command_install_service(args: argparse.Namespace) -> int:
    database = absolute_path(args.database)
    log_dir = Path(database).parent
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = absolute_path(args.stdout or log_dir / "ledger.out.log")
    stderr_path = absolute_path(args.stderr or log_dir / "ledger.err.log")
    plist_path = Path(args.plist).expanduser() if args.plist else default_plist_path(args.label)
    payload = build_launchd_plist(
        label=args.label,
        python=sys.executable,
        working_directory=absolute_path(args.working_directory),
        database=database,
        controller=args.controller,
        interval=args.interval,
        secret=args.secret,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )
    target = write_launchd_plist(plist_path, payload)
    if not args.no_load:
        bootstrap_service(args.label, target)
    print(f"wrote {target}")
    if args.no_load:
        print("service not loaded (--no-load)")
    else:
        print(f"loaded {args.label}")
    return 0


def command_uninstall_service(args: argparse.Namespace) -> int:
    plist_path = Path(args.plist).expanduser() if args.plist else default_plist_path(args.label)
    bootout_service(args.label, plist_path)
    if not args.keep_plist and plist_path.exists():
        plist_path.unlink()
        print(f"removed {plist_path}")
    else:
        print(f"left plist at {plist_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="clash-verge-traffic-ledger")
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

    status = subparsers.add_parser("status", help="Print database and daily ledger status")
    add_database_arg(status)
    status.add_argument("--date", default=None, help="Status date, defaults to today")
    status.add_argument("--service-label", default=DEFAULT_LABEL)
    status.add_argument("--no-service-check", action="store_true")
    status.set_defaults(func=command_status)

    anomalies = subparsers.add_parser("anomalies", help="Print simple traffic anomaly hints")
    add_database_arg(anomalies)
    anomalies.add_argument("--date", default=None, help="Analysis date, defaults to today")
    anomalies.add_argument("--byte-threshold", type=int, default=DEFAULT_ANOMALY_BYTE_THRESHOLD)
    anomalies.add_argument("--unknown-ratio-threshold", type=float, default=0.25)
    anomalies.add_argument("--spike-multiplier", type=float, default=3.0)
    anomalies.set_defaults(func=command_anomalies)

    web = subparsers.add_parser("web", help="Serve a read-only local dashboard")
    add_database_arg(web)
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8765)
    web.set_defaults(func=command_web)

    prune = subparsers.add_parser("prune", help="Delete raw delta rows before a date")
    add_database_arg(prune)
    prune.add_argument("--before", required=True, help="Delete raw rows older than this YYYY-MM-DD date")
    prune.add_argument("--dry-run", action="store_true")
    prune.set_defaults(func=command_prune)

    compact = subparsers.add_parser("compact", help="Compact old raw deltas while preserving rollups")
    add_database_arg(compact)
    compact.add_argument("--before", required=True, help="Compact raw rows older than this YYYY-MM-DD date")
    compact.add_argument("--dry-run", action="store_true")
    compact.set_defaults(func=command_compact)

    install_service = subparsers.add_parser("install-service", help="Install a launchd sampler service")
    add_controller_args(install_service)
    add_database_arg(install_service)
    install_service.add_argument("--interval", type=float, default=1.0)
    install_service.add_argument("--label", default=DEFAULT_LABEL)
    install_service.add_argument("--plist", default=None, help="LaunchAgent plist path")
    install_service.add_argument("--working-directory", default=str(Path.cwd()))
    install_service.add_argument("--stdout", default=None, help="Sampler stdout log path")
    install_service.add_argument("--stderr", default=None, help="Sampler stderr log path")
    install_service.add_argument("--no-load", action="store_true", help="Write plist without loading it")
    install_service.set_defaults(func=command_install_service)

    uninstall_service = subparsers.add_parser(
        "uninstall-service",
        help="Unload and remove the launchd sampler service",
    )
    uninstall_service.add_argument("--label", default=DEFAULT_LABEL)
    uninstall_service.add_argument("--plist", default=None, help="LaunchAgent plist path")
    uninstall_service.add_argument("--keep-plist", action="store_true")
    uninstall_service.set_defaults(func=command_uninstall_service)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
