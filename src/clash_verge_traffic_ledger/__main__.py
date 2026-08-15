from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from .audit import (
    DEFAULT_BASELINE_DAYS,
    DEFAULT_WINDOW_DAYS,
    audit_traffic,
    build_evidence,
    find_case,
)
from .anomalies import detect_anomalies, format_anomalies
from .client import ControllerConfig, DEFAULT_UNIX_SOCKET, MihomoClient, needs_process_lookup
from .contracts import (
    EXIT_DATA_ERROR,
    EXIT_OK,
    EXIT_UNAVAILABLE,
    envelope,
    error_item,
    render_json,
)
from .health import inspect_health, summarize_attribution
from .monitor import Sampler
from .process_lookup import capture_process_lookup, lsof_path
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
    parser.add_argument("--secret-file", default=None, help="Read the controller secret from a file")
    parser.add_argument("--timeout", type=float, default=5.0, help="Controller timeout in seconds")


def add_database_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--database", default=DEFAULT_DATABASE, help="SQLite database path")


def add_json_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")


def absolute_path(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


def controller_config_from_args(args: argparse.Namespace) -> ControllerConfig:
    if args.secret and args.secret_file:
        raise ValueError("use either --secret or --secret-file, not both")
    secret = args.secret or os.environ.get("MIHOMO_SECRET")
    if args.secret_file:
        secret_path = Path(args.secret_file).expanduser()
        secret = secret_path.read_text(encoding="utf-8").strip()
        if not secret:
            raise ValueError(f"secret file is empty: {secret_path}")
    return ControllerConfig(
        controller=args.controller,
        secret=secret,
        timeout=args.timeout,
    )


def build_client(args: argparse.Namespace) -> MihomoClient:
    return MihomoClient(controller_config_from_args(args))


def command_doctor(args: argparse.Namespace) -> int:
    client = build_client(args)
    try:
        version = client.version()
        raw_connections = client.raw_connections()
        items = [
            item for item in (raw_connections.get("connections") or []) if isinstance(item, dict)
        ]
        process_lookup = (
            capture_process_lookup(timeout=min(args.timeout, 2.0))
            if needs_process_lookup(items)
            else None
        )
        attribution = summarize_attribution(items, process_lookup=process_lookup)
    except Exception as exc:
        print(f"controller: failed ({exc})", file=sys.stderr)
        return 1

    total = len(items)
    known = int(attribution["known_connections"])
    lsof = lsof_path()

    print(f"controller: ok ({args.controller})")
    print(f"version: {version}")
    print(f"connections: {total}")
    print(f"process attribution: {known}/{total} known")
    print(f"attribution status: {attribution['status']}")
    print(f"lsof: {lsof or 'not found'}")
    return 0


def command_run(args: argparse.Namespace) -> int:
    client = build_client(args)
    store = LedgerStore(args.database)
    sampler = Sampler(
        client=client,
        store=store,
        interval=args.interval,
        max_backoff=args.max_backoff,
    )
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


def _machine_error(
    operation: str,
    code: str,
    exc: Exception,
    *,
    pretty: bool,
    exit_code: int,
    retryable: bool = False,
) -> int:
    payload = envelope(
        operation,
        None,
        ok=False,
        errors=[error_item(code, str(exc), retryable=retryable)],
    )
    print(render_json(payload, pretty=pretty))
    return exit_code


def command_health(args: argparse.Namespace) -> int:
    try:
        data, warnings, next_actions = inspect_health(
            args.database,
            controller_config_from_args(args),
            service_label=None if args.no_service_check else args.service_label,
            max_sample_age_seconds=args.max_sample_age,
            check_controller=not args.no_controller_check,
        )
    except Exception as exc:
        return _machine_error(
            "health",
            "health_check_failed",
            exc,
            pretty=args.pretty,
            exit_code=EXIT_UNAVAILABLE,
            retryable=True,
        )
    print(
        render_json(
            envelope("health", data, warnings=warnings, next_actions=next_actions),
            pretty=args.pretty,
        )
    )
    return EXIT_OK


def command_audit(args: argparse.Namespace) -> int:
    try:
        store = LedgerStore(args.database, read_only=True)
        data, warnings, next_actions = audit_traffic(
            store,
            args.end_date or datetime.now().astimezone().date().isoformat(),
            window_days=args.since,
            baseline_days=args.baseline,
            case_limit=args.limit,
        )
    except FileNotFoundError as exc:
        return _machine_error(
            "audit",
            "database_missing",
            exc,
            pretty=args.pretty,
            exit_code=EXIT_UNAVAILABLE,
        )
    except (ValueError, LookupError) as exc:
        return _machine_error(
            "audit",
            "invalid_audit_request",
            exc,
            pretty=args.pretty,
            exit_code=EXIT_DATA_ERROR,
        )
    except Exception as exc:
        return _machine_error(
            "audit",
            "audit_failed",
            exc,
            pretty=args.pretty,
            exit_code=EXIT_DATA_ERROR,
            retryable=True,
        )
    print(
        render_json(
            envelope("audit", data, warnings=warnings, next_actions=next_actions),
            pretty=args.pretty,
        )
    )
    return EXIT_OK


def command_evidence(args: argparse.Namespace) -> int:
    try:
        store = LedgerStore(args.database, read_only=True)
        case = find_case(store, args.case_id)
        data = build_evidence(store, case, limit=args.limit)
    except FileNotFoundError as exc:
        return _machine_error(
            "evidence",
            "database_missing",
            exc,
            pretty=args.pretty,
            exit_code=EXIT_UNAVAILABLE,
        )
    except (ValueError, LookupError) as exc:
        return _machine_error(
            "evidence",
            "case_not_found",
            exc,
            pretty=args.pretty,
            exit_code=EXIT_DATA_ERROR,
        )
    except Exception as exc:
        return _machine_error(
            "evidence",
            "evidence_failed",
            exc,
            pretty=args.pretty,
            exit_code=EXIT_DATA_ERROR,
            retryable=True,
        )
    print(render_json(envelope("evidence", data), pretty=args.pretty))
    return EXIT_OK


def command_maintenance(args: argparse.Namespace) -> int:
    try:
        store = LedgerStore(args.database, read_only=not args.apply)
        matching_rows = store.raw_delta_count_before(args.before)
        warnings = []
        next_actions = []
        result: dict[str, int] | None = None
        if args.apply:
            if args.mode == "compact":
                result = store.compact_raw_before(args.before)
            else:
                deleted = store.delete_raw_before(args.before)
                result = {
                    "deleted_raw_rows": deleted,
                    "remaining_raw_rows": store.raw_delta_count(),
                    "preserved_rollup_dates": store.rollup_date_count(),
                }
        else:
            next_actions.append(
                {
                    "code": "confirm_maintenance",
                    "description": "After explicit user confirmation, rerun with --apply.",
                    "parameters": {"mode": args.mode, "before": args.before},
                }
            )
        if args.mode == "prune":
            warnings.append(
                {
                    "code": "raw_evidence_deletion",
                    "message": "Pruning removes raw evidence; daily rollups remain but case drill-down may be limited.",
                }
            )
        data = {
            "mode": args.mode,
            "before": args.before,
            "dry_run": not args.apply,
            "matching_raw_rows": matching_rows,
            "result": result,
        }
    except FileNotFoundError as exc:
        return _machine_error(
            "maintenance",
            "database_missing",
            exc,
            pretty=args.pretty,
            exit_code=EXIT_UNAVAILABLE,
        )
    except Exception as exc:
        return _machine_error(
            "maintenance",
            "maintenance_failed",
            exc,
            pretty=args.pretty,
            exit_code=EXIT_DATA_ERROR,
            retryable=True,
        )
    print(
        render_json(
            envelope("maintenance", data, warnings=warnings, next_actions=next_actions),
            pretty=args.pretty,
        )
    )
    return EXIT_OK


def command_web(args: argparse.Namespace) -> int:
    store = LedgerStore(args.database)
    print(f"serving http://{args.host}:{args.port}/")
    serve_dashboard(store, args.host, args.port)
    return 0


def command_prune(args: argparse.Namespace) -> int:
    store = LedgerStore(args.database, read_only=not args.apply)
    count = store.raw_delta_count_before(args.before)
    if not args.apply:
        print(f"would delete {count} raw delta rows before {args.before}")
        return 0
    deleted = store.delete_raw_before(args.before)
    print(f"deleted {deleted} raw delta rows before {args.before}")
    return 0


def command_compact(args: argparse.Namespace) -> int:
    store = LedgerStore(args.database, read_only=not args.apply)
    count = store.raw_delta_count_before(args.before)
    if not args.apply:
        print(f"would compact {count} raw delta rows before {args.before}")
        return 0
    result = store.compact_raw_before(args.before)
    print(
        "compacted {deleted} raw delta rows before {before}; "
        "{remaining} raw rows remain; {dates} rollup dates preserved; "
        "reclaimed {reclaimed} bytes".format(
            deleted=result["deleted_raw_rows"],
            before=args.before,
            remaining=result["remaining_raw_rows"],
            dates=result["preserved_rollup_dates"],
            reclaimed=result["reclaimed_bytes"],
        )
    )
    return 0


def command_install_service(args: argparse.Namespace) -> int:
    if args.secret:
        print(
            "install-service does not persist --secret; use a mode-600 --secret-file instead",
            file=sys.stderr,
        )
        return 1
    secret_file = None
    if args.secret_file:
        path = Path(args.secret_file).expanduser().resolve()
        if not path.is_file():
            print(f"secret file not found: {path}", file=sys.stderr)
            return 1
        if path.stat().st_mode & 0o077:
            print(f"secret file must not be accessible by group or others: {path}", file=sys.stderr)
            return 1
        secret_file = str(path)
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
        max_backoff=args.max_backoff,
        secret_file=secret_file,
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
    run.add_argument("--max-backoff", type=float, default=30.0, help="Maximum retry delay")
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

    health = subparsers.add_parser("health", help="Print machine-readable runtime health")
    add_controller_args(health)
    add_database_arg(health)
    add_json_arg(health)
    health.add_argument("--service-label", default=DEFAULT_LABEL)
    health.add_argument("--max-sample-age", type=float, default=180.0)
    health.add_argument("--no-controller-check", action="store_true")
    health.add_argument("--no-service-check", action="store_true")
    health.set_defaults(func=command_health)

    audit = subparsers.add_parser("audit", help="Audit a traffic window and emit JSON cases")
    add_database_arg(audit)
    add_json_arg(audit)
    audit.add_argument("--end-date", default=None, help="Window end date, defaults to today")
    audit.add_argument("--since", type=int, default=DEFAULT_WINDOW_DAYS, help="Window days")
    audit.add_argument("--baseline", type=int, default=DEFAULT_BASELINE_DAYS)
    audit.add_argument("--limit", type=int, default=50, help="Maximum returned cases")
    audit.set_defaults(func=command_audit)

    evidence = subparsers.add_parser("evidence", help="Expand one audit case into JSON evidence")
    add_database_arg(evidence)
    add_json_arg(evidence)
    evidence.add_argument("--case-id", required=True)
    evidence.add_argument("--limit", type=int, default=20, help="Maximum raw evidence groups")
    evidence.set_defaults(func=command_evidence)

    maintenance = subparsers.add_parser(
        "maintenance",
        help="Plan or apply raw-data retention with JSON output",
    )
    add_database_arg(maintenance)
    add_json_arg(maintenance)
    maintenance.add_argument("--before", required=True)
    maintenance.add_argument("--mode", choices=["compact", "prune"], default="compact")
    maintenance_mode = maintenance.add_mutually_exclusive_group()
    maintenance_mode.add_argument("--apply", action="store_true")
    maintenance_mode.add_argument("--dry-run", action="store_true")
    maintenance.set_defaults(func=command_maintenance)

    web = subparsers.add_parser("web", help="Serve a read-only local dashboard")
    add_database_arg(web)
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8765)
    web.set_defaults(func=command_web)

    prune = subparsers.add_parser("prune", help="Plan or apply raw delta deletion")
    add_database_arg(prune)
    prune.add_argument("--before", required=True, help="Delete raw rows older than this YYYY-MM-DD date")
    prune_mode = prune.add_mutually_exclusive_group()
    prune_mode.add_argument("--apply", action="store_true", help="Apply the destructive deletion")
    prune_mode.add_argument("--dry-run", action="store_true", help="Preview only (the default)")
    prune.set_defaults(func=command_prune)

    compact = subparsers.add_parser(
        "compact",
        help="Plan or apply raw compaction while preserving rollups",
    )
    add_database_arg(compact)
    compact.add_argument("--before", required=True, help="Compact raw rows older than this YYYY-MM-DD date")
    compact_mode = compact.add_mutually_exclusive_group()
    compact_mode.add_argument("--apply", action="store_true", help="Apply deletion and VACUUM")
    compact_mode.add_argument("--dry-run", action="store_true", help="Preview only (the default)")
    compact.set_defaults(func=command_compact)

    install_service = subparsers.add_parser("install-service", help="Install a launchd sampler service")
    add_controller_args(install_service)
    add_database_arg(install_service)
    install_service.add_argument("--interval", type=float, default=1.0)
    install_service.add_argument("--max-backoff", type=float, default=30.0)
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
