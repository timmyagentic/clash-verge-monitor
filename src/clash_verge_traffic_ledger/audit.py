from __future__ import annotations

import hashlib
import re
import statistics
from dataclasses import asdict, dataclass
from datetime import date as Date
from datetime import datetime, timedelta, timezone
from typing import Any

from .contracts import action_item, warning_item
from .store import LedgerStore


POLICY_VERSION = 2
DEFAULT_WINDOW_DAYS = 7
DEFAULT_BASELINE_DAYS = 30
MIN_BASELINE_DAYS = 7
DEFAULT_ABSOLUTE_DAILY_BYTES = 500 * 1024 * 1024
DEFAULT_MIN_SPIKE_BYTES = 500 * 1024 * 1024
DEFAULT_MIN_UPLOAD_SPIKE_BYTES = 200 * 1024 * 1024
DEFAULT_UNKNOWN_RATIO = 0.25
DEFAULT_MIN_UNKNOWN_BYTES = 100 * 1024 * 1024
DEFAULT_SPIKE_RATIO = 3.0

_CASE_ID_PATTERN = re.compile(
    r"^v(?P<policy>\d+)-(?P<end>\d{8})-(?P<window>\d+)d-(?P<baseline>\d+)d-(?P<digest>[0-9a-f]{12})$"
)
_SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


@dataclass(frozen=True)
class AnomalyCase:
    case_id: str
    code: str
    severity: str
    confidence: str
    description: str
    window: dict[str, Any]
    subject: dict[str, str]
    observed_bytes: int
    observed_upload_bytes: int
    observed_download_bytes: int
    baseline: dict[str, Any]
    ratio: float | None
    evidence: list[dict[str, Any]]
    limitations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _date_window(end_date: str, days: int) -> tuple[str, str]:
    if days < 1:
        raise ValueError("days must be at least 1")
    end = Date.fromisoformat(end_date)
    start = end - timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


def _case_id(
    code: str,
    subject_type: str,
    subject: str,
    end_date: str,
    window_days: int,
    baseline_days: int,
) -> str:
    identity = "|".join(
        [str(POLICY_VERSION), end_date, str(window_days), str(baseline_days), code, subject_type, subject]
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return f"v{POLICY_VERSION}-{end_date.replace('-', '')}-{window_days}d-{baseline_days}d-{digest}"


def parse_case_id(case_id: str) -> dict[str, Any]:
    match = _CASE_ID_PATTERN.fullmatch(case_id)
    if not match:
        raise ValueError(f"invalid case id: {case_id}")
    parts = match.groupdict()
    if int(parts["policy"]) != POLICY_VERSION:
        raise ValueError(f"unsupported case policy version: {parts['policy']}")
    raw_end = parts["end"]
    return {
        "policy_version": int(parts["policy"]),
        "end_date": f"{raw_end[:4]}-{raw_end[4:6]}-{raw_end[6:]}",
        "window_days": int(parts["window"]),
        "baseline_days": int(parts["baseline"]),
    }


def _subject_map(rows: list[dict[str, int | str]]) -> dict[str, dict[str, dict[str, int]]]:
    mapped: dict[str, dict[str, dict[str, int]]] = {}
    for row in rows:
        subject = str(row["subject"])
        mapped.setdefault(subject, {})[str(row["date"])] = {
            "upload_bytes": int(row["upload_bytes"]),
            "download_bytes": int(row["download_bytes"]),
            "total_bytes": int(row["total_bytes"]),
        }
    return mapped


def _values(
    subject_rows: dict[str, dict[str, int]],
    active_dates: list[str],
    key: str,
) -> list[int]:
    return [int(subject_rows.get(date, {}).get(key, 0)) for date in active_dates]


def _stats(values: list[int], expected_days: int) -> dict[str, Any]:
    if not values:
        return {
            "active_days": 0,
            "total_bytes": 0,
            "daily_mean_bytes": 0.0,
            "daily_median_bytes": 0.0,
            "daily_mad_bytes": 0.0,
            "daily_max_bytes": 0,
            "expected_window_bytes": 0,
        }
    median = float(statistics.median(values))
    mad = float(statistics.median(abs(value - median) for value in values))
    mean = float(statistics.fmean(values))
    return {
        "active_days": len(values),
        "total_bytes": int(sum(values)),
        "daily_mean_bytes": round(mean, 3),
        "daily_median_bytes": round(median, 3),
        "daily_mad_bytes": round(mad, 3),
        "daily_max_bytes": int(max(values)),
        "expected_window_bytes": int(round(mean * expected_days)),
    }


def _confidence(active_baseline_days: int) -> str:
    if active_baseline_days >= 14:
        return "high"
    if active_baseline_days >= MIN_BASELINE_DAYS:
        return "medium"
    return "low"


def _ratio(observed_daily: float, baseline_daily: float) -> float | None:
    if baseline_daily <= 0:
        return None
    return round(observed_daily / baseline_daily, 3)


def _severity(ratio: float | None, observed_bytes: int) -> str:
    if ratio is not None and ratio >= 10 and observed_bytes >= 5 * 1024 * 1024 * 1024:
        return "critical"
    return "warning"


def _baseline_limitations(active_days: int, requested_days: int) -> list[str]:
    limitations: list[str] = []
    if active_days < MIN_BASELINE_DAYS:
        limitations.append(
            f"Only {active_days} active baseline days are available; robust change detection needs at least {MIN_BASELINE_DAYS}."
        )
    elif active_days < requested_days:
        limitations.append(
            f"The requested {requested_days}-day baseline contains {active_days} active traffic days."
        )
    return limitations


def _audit_freshness(
    store: LedgerStore,
    end_date: str,
    *,
    now: datetime | None,
    max_sample_age_seconds: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    timestamp = now or datetime.now().astimezone()
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    latest_sample = store.latest_delta_timestamp()
    latest_date: str | None = None
    sample_age_seconds: float | None = None
    if latest_sample:
        sampled_at = datetime.fromisoformat(latest_sample)
        if sampled_at.tzinfo is None:
            sampled_at = sampled_at.replace(tzinfo=timezone.utc)
        latest_date = sampled_at.astimezone(timestamp.tzinfo).date().isoformat()
        sample_age_seconds = max(
            0.0,
            (timestamp.astimezone(timezone.utc) - sampled_at.astimezone(timezone.utc)).total_seconds(),
        )

    today = timestamp.date().isoformat()
    warnings: list[dict[str, Any]] = []
    if end_date == today and latest_date == end_date:
        window_end_status = "partial"
        warnings.append(
            warning_item(
                "partial_window_day",
                "The audit window includes the current partial day.",
                observed_through=latest_sample,
            )
        )
        if sample_age_seconds is not None and sample_age_seconds > max_sample_age_seconds:
            warnings.append(
                warning_item(
                    "sample_stale",
                    "The latest sample in the current audit window is stale.",
                    max_sample_age_seconds=max_sample_age_seconds,
                )
            )
    elif latest_date is None or latest_date < end_date:
        window_end_status = "missing"
        warnings.append(
            warning_item(
                "window_after_latest_sample",
                "The requested audit window extends beyond the latest retained sample.",
                latest_sample=latest_sample,
            )
        )
        if end_date == today and sample_age_seconds is not None and sample_age_seconds > max_sample_age_seconds:
            warnings.append(
                warning_item(
                    "sample_stale",
                    "The latest sample in the current audit window is stale.",
                    max_sample_age_seconds=max_sample_age_seconds,
                )
            )
    else:
        window_end_status = "complete"

    return (
        {
            "latest_sample": latest_sample,
            "sample_age_seconds": round(sample_age_seconds, 3)
            if sample_age_seconds is not None
            else None,
            "window_end_status": window_end_status,
            "observed_through": end_date if window_end_status == "complete" else latest_sample,
        },
        warnings,
    )


def _make_case(
    *,
    code: str,
    severity: str,
    description: str,
    subject_type: str,
    subject: str,
    end_date: str,
    window_days: int,
    baseline_days: int,
    window_start: str,
    observed_upload: int,
    observed_download: int,
    baseline: dict[str, Any],
    ratio: float | None,
    evidence: list[dict[str, Any]],
    limitations: list[str],
) -> AnomalyCase:
    observed = observed_upload + observed_download
    return AnomalyCase(
        case_id=_case_id(code, subject_type, subject, end_date, window_days, baseline_days),
        code=code,
        severity=severity,
        confidence=_confidence(int(baseline["active_days"])),
        description=description,
        window={"start": window_start, "end": end_date, "days": window_days},
        subject={"type": subject_type, "value": subject},
        observed_bytes=observed,
        observed_upload_bytes=observed_upload,
        observed_download_bytes=observed_download,
        baseline=baseline,
        ratio=ratio,
        evidence=evidence,
        limitations=limitations,
    )


def _detect_subject_cases(
    *,
    subject_type: str,
    current: dict[str, dict[str, dict[str, int]]],
    baseline: dict[str, dict[str, dict[str, int]]],
    current_dates: list[str],
    baseline_dates: list[str],
    window_start: str,
    end_date: str,
    window_days: int,
    baseline_days: int,
    absolute_daily_bytes: int,
    min_spike_bytes: int,
    min_upload_spike_bytes: int,
    spike_ratio: float,
) -> list[AnomalyCase]:
    cases: list[AnomalyCase] = []
    subject_label = "process" if subject_type == "process" else "host"
    current_day_count = max(len(current_dates), 1)
    baseline_limitations = _baseline_limitations(len(baseline_dates), baseline_days)

    for subject, current_rows in current.items():
        current_totals = _values(current_rows, current_dates, "total_bytes")
        current_uploads = _values(current_rows, current_dates, "upload_bytes")
        observed_upload = sum(current_uploads)
        observed_total = sum(current_totals)
        observed_download = observed_total - observed_upload
        if observed_total <= 0:
            continue

        baseline_rows = baseline.get(subject, {})
        baseline_totals = _values(baseline_rows, baseline_dates, "total_bytes")
        baseline_uploads = _values(baseline_rows, baseline_dates, "upload_bytes")
        total_stats = _stats(baseline_totals, current_day_count)
        observed_daily = observed_total / current_day_count
        baseline_daily = float(total_stats["daily_mean_bytes"])
        traffic_ratio = _ratio(observed_daily, baseline_daily)

        if observed_total >= absolute_daily_bytes * current_day_count:
            cases.append(
                _make_case(
                    code=f"high_{subject_label}_usage",
                    severity="info",
                    description=f"{subject_label.capitalize()} traffic exceeded the absolute volume threshold.",
                    subject_type=subject_type,
                    subject=subject,
                    end_date=end_date,
                    window_days=window_days,
                    baseline_days=baseline_days,
                    window_start=window_start,
                    observed_upload=observed_upload,
                    observed_download=observed_download,
                    baseline=total_stats,
                    ratio=traffic_ratio,
                    evidence=[
                        {"metric": "window_total_bytes", "value": observed_total},
                        {
                            "metric": "absolute_window_threshold_bytes",
                            "value": absolute_daily_bytes * current_day_count,
                        },
                    ],
                    limitations=baseline_limitations
                    + ["High volume alone does not establish malicious or unwanted traffic."],
                )
            )

        if int(total_stats["total_bytes"]) == 0:
            if observed_total >= min_spike_bytes:
                cases.append(
                    _make_case(
                        code=f"new_{subject_label}",
                        severity="warning",
                        description=f"A {subject_label} with no baseline traffic transferred significant data.",
                        subject_type=subject_type,
                        subject=subject,
                        end_date=end_date,
                        window_days=window_days,
                        baseline_days=baseline_days,
                        window_start=window_start,
                        observed_upload=observed_upload,
                        observed_download=observed_download,
                        baseline=total_stats,
                        ratio=None,
                        evidence=[
                            {"metric": "window_total_bytes", "value": observed_total},
                            {"metric": "baseline_total_bytes", "value": 0},
                        ],
                        limitations=baseline_limitations,
                    )
                )
            continue

        if len(baseline_dates) < MIN_BASELINE_DAYS or observed_total < min_spike_bytes:
            continue

        median = float(total_stats["daily_median_bytes"])
        mad = float(total_stats["daily_mad_bytes"])
        robust_sigma = 1.4826 * mad
        robust_limit = median + max(3 * robust_sigma, 50 * 1024 * 1024)
        ratio_limit = max(baseline_daily, median, 1.0) * spike_ratio
        spike_limit = max(robust_limit, ratio_limit)
        spike_days = sum(1 for value in current_totals if value >= spike_limit)
        if observed_daily >= spike_limit and traffic_ratio is not None and traffic_ratio >= spike_ratio:
            code = f"sustained_{subject_label}_spike" if spike_days >= 3 else f"{subject_label}_spike"
            cases.append(
                _make_case(
                    code=code,
                    severity=_severity(traffic_ratio, observed_total),
                    description=f"{subject_label.capitalize()} traffic exceeded its robust daily baseline.",
                    subject_type=subject_type,
                    subject=subject,
                    end_date=end_date,
                    window_days=window_days,
                    baseline_days=baseline_days,
                    window_start=window_start,
                    observed_upload=observed_upload,
                    observed_download=observed_download,
                    baseline=total_stats,
                    ratio=traffic_ratio,
                    evidence=[
                        {"metric": "current_daily_average_bytes", "value": int(observed_daily)},
                        {"metric": "baseline_daily_mean_bytes", "value": int(baseline_daily)},
                        {"metric": "robust_daily_limit_bytes", "value": int(spike_limit)},
                        {"metric": "days_above_limit", "value": spike_days},
                    ],
                    limitations=baseline_limitations,
                )
            )

        upload_stats = _stats(baseline_uploads, current_day_count)
        baseline_upload_daily = float(upload_stats["daily_mean_bytes"])
        observed_upload_daily = observed_upload / current_day_count
        upload_ratio = _ratio(observed_upload_daily, baseline_upload_daily)
        upload_median = float(upload_stats["daily_median_bytes"])
        upload_mad = float(upload_stats["daily_mad_bytes"])
        upload_limit = max(
            upload_median + max(3 * 1.4826 * upload_mad, 25 * 1024 * 1024),
            max(baseline_upload_daily, upload_median, 1.0) * spike_ratio,
        )
        if (
            observed_upload >= min_upload_spike_bytes
            and upload_ratio is not None
            and upload_ratio >= spike_ratio
            and observed_upload_daily >= upload_limit
        ):
            cases.append(
                _make_case(
                    code=f"{subject_label}_upload_spike",
                    severity=_severity(upload_ratio, observed_upload),
                    description=f"{subject_label.capitalize()} upload traffic exceeded its robust baseline.",
                    subject_type=subject_type,
                    subject=subject,
                    end_date=end_date,
                    window_days=window_days,
                    baseline_days=baseline_days,
                    window_start=window_start,
                    observed_upload=observed_upload,
                    observed_download=observed_download,
                    baseline=upload_stats,
                    ratio=upload_ratio,
                    evidence=[
                        {"metric": "window_upload_bytes", "value": observed_upload},
                        {"metric": "current_daily_upload_average_bytes", "value": int(observed_upload_daily)},
                        {"metric": "robust_daily_upload_limit_bytes", "value": int(upload_limit)},
                    ],
                    limitations=baseline_limitations,
                )
            )

    return cases


def audit_traffic(
    store: LedgerStore,
    end_date: str,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    baseline_days: int = DEFAULT_BASELINE_DAYS,
    case_limit: int = 50,
    absolute_daily_bytes: int = DEFAULT_ABSOLUTE_DAILY_BYTES,
    min_spike_bytes: int = DEFAULT_MIN_SPIKE_BYTES,
    min_upload_spike_bytes: int = DEFAULT_MIN_UPLOAD_SPIKE_BYTES,
    unknown_ratio_threshold: float = DEFAULT_UNKNOWN_RATIO,
    min_unknown_bytes: int = DEFAULT_MIN_UNKNOWN_BYTES,
    spike_ratio: float = DEFAULT_SPIKE_RATIO,
    now: datetime | None = None,
    max_sample_age_seconds: float = 180.0,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    if window_days < 1 or baseline_days < 1 or case_limit < 1:
        raise ValueError("window, baseline, and case limit must be positive")

    window_start, window_end = _date_window(end_date, window_days)
    baseline_end = (Date.fromisoformat(window_start) - timedelta(days=1)).isoformat()
    baseline_start, _ = _date_window(baseline_end, baseline_days)
    current_dates = store.active_dates(window_start, window_end)
    baseline_dates = store.active_dates(baseline_start, baseline_end)
    freshness, freshness_warnings = _audit_freshness(
        store,
        window_end,
        now=now,
        max_sample_age_seconds=max_sample_age_seconds,
    )

    current_process = _subject_map(store.subject_daily("process", window_start, window_end))
    baseline_process = _subject_map(store.subject_daily("process", baseline_start, baseline_end))
    current_host = _subject_map(store.subject_daily("host", window_start, window_end))
    baseline_host = _subject_map(store.subject_daily("host", baseline_start, baseline_end))

    cases = _detect_subject_cases(
        subject_type="process",
        current=current_process,
        baseline=baseline_process,
        current_dates=current_dates,
        baseline_dates=baseline_dates,
        window_start=window_start,
        end_date=window_end,
        window_days=window_days,
        baseline_days=baseline_days,
        absolute_daily_bytes=absolute_daily_bytes,
        min_spike_bytes=min_spike_bytes,
        min_upload_spike_bytes=min_upload_spike_bytes,
        spike_ratio=spike_ratio,
    )
    cases.extend(
        _detect_subject_cases(
            subject_type="host",
            current=current_host,
            baseline=baseline_host,
            current_dates=current_dates,
            baseline_dates=baseline_dates,
            window_start=window_start,
            end_date=window_end,
            window_days=window_days,
            baseline_days=baseline_days,
            absolute_daily_bytes=absolute_daily_bytes,
            min_spike_bytes=min_spike_bytes,
            min_upload_spike_bytes=min_upload_spike_bytes,
            spike_ratio=spike_ratio,
        )
    )

    current_process_total = sum(
        int(values.get(date, {}).get("total_bytes", 0))
        for values in current_process.values()
        for date in current_dates
    )
    unknown_total = sum(
        int(current_process.get("unknown", {}).get(date, {}).get("total_bytes", 0))
        for date in current_dates
    )
    baseline_process_total = sum(
        int(values.get(date, {}).get("total_bytes", 0))
        for values in baseline_process.values()
        for date in baseline_dates
    )
    baseline_unknown_total = sum(
        int(baseline_process.get("unknown", {}).get(date, {}).get("total_bytes", 0))
        for date in baseline_dates
    )
    unknown_ratio = unknown_total / current_process_total if current_process_total else 0.0
    baseline_unknown_ratio = (
        baseline_unknown_total / baseline_process_total if baseline_process_total else 0.0
    )
    attribution_degraded = bool(
        unknown_total >= min_unknown_bytes and unknown_ratio >= unknown_ratio_threshold
    )
    if attribution_degraded:
        baseline_stats = _stats(
            _values(
                baseline_process.get("unknown", {}),
                baseline_dates,
                "total_bytes",
            ),
            max(len(current_dates), 1),
        )
        baseline_stats["unknown_ratio"] = round(baseline_unknown_ratio, 6)
        materially_worsened = bool(
            (baseline_process_total == 0 and unknown_ratio >= unknown_ratio_threshold)
            or (
                baseline_process_total > 0
                and unknown_ratio - baseline_unknown_ratio >= 0.10
                and (
                    baseline_unknown_ratio == 0
                    or unknown_ratio / baseline_unknown_ratio >= 1.25
                )
            )
        )
        severity = "warning" if materially_worsened else "info"
        cases.append(
            _make_case(
                code="unknown_process_ratio",
                severity=severity,
                description="A large share of traffic could not be attributed to a process.",
                subject_type="process",
                subject="unknown",
                end_date=window_end,
                window_days=window_days,
                baseline_days=baseline_days,
                window_start=window_start,
                observed_upload=sum(
                    int(current_process.get("unknown", {}).get(date, {}).get("upload_bytes", 0))
                    for date in current_dates
                ),
                observed_download=sum(
                    int(current_process.get("unknown", {}).get(date, {}).get("download_bytes", 0))
                    for date in current_dates
                ),
                baseline=baseline_stats,
                ratio=round(unknown_ratio / baseline_unknown_ratio, 3)
                if baseline_unknown_ratio > 0
                else None,
                evidence=[
                    {"metric": "unknown_ratio", "value": round(unknown_ratio, 6)},
                    {"metric": "unknown_bytes", "value": unknown_total},
                    {"metric": "window_total_bytes", "value": current_process_total},
                ],
                limitations=_baseline_limitations(len(baseline_dates), baseline_days)
                + ["Unknown attribution is a visibility gap, not proof of malicious traffic."],
            )
        )

    cases.sort(
        key=lambda item: (
            _SEVERITY_ORDER.get(item.severity, 9),
            -item.observed_bytes,
            item.code,
            item.subject["value"],
        )
    )
    total_case_count = len(cases)
    cases = cases[:case_limit]
    warnings: list[dict[str, Any]] = list(freshness_warnings)
    next_actions: list[dict[str, Any]] = []
    if not current_dates:
        warnings.append(warning_item("no_window_data", "No traffic rollups exist in the requested window."))
    if len(baseline_dates) < MIN_BASELINE_DAYS:
        warnings.append(
            warning_item(
                "insufficient_baseline",
                "Robust anomaly comparison has insufficient active baseline days.",
                active_days=len(baseline_dates),
                required_days=MIN_BASELINE_DAYS,
            )
        )
    if total_case_count > case_limit:
        warnings.append(
            warning_item(
                "cases_truncated",
                "The case list was truncated.",
                total_cases=total_case_count,
                returned_cases=case_limit,
            )
        )

    if attribution_degraded:
        warnings.append(
            warning_item(
                "process_attribution_degraded",
                "A significant share of traffic could not be attributed to a process.",
                unknown_ratio=round(unknown_ratio, 6),
                unknown_bytes=unknown_total,
            )
        )
        next_actions.append(
            action_item(
                "inspect_process_attribution",
                "Inspect source endpoints and unknown-process evidence before interpreting process totals.",
            )
        )

    alert_cases = [
        case
        for case in cases
        if case.code != "unknown_process_ratio" and case.severity in {"warning", "critical"}
    ]
    if alert_cases:
        verdict = "anomalies_detected"
        next_actions.insert(
            0,
            action_item(
                "inspect_case",
                "Run evidence for the highest-severity case before drawing a conclusion.",
                case_id=alert_cases[0].case_id,
            )
        )
    elif not current_dates or len(baseline_dates) < MIN_BASELINE_DAYS:
        verdict = "insufficient_data"
    else:
        verdict = "no_anomalies"

    process_totals = sorted(
        (
            {
                "subject": subject,
                "total_bytes": sum(
                    int(rows.get(date, {}).get("total_bytes", 0)) for date in current_dates
                ),
            }
            for subject, rows in current_process.items()
        ),
        key=lambda item: int(item["total_bytes"]),
        reverse=True,
    )
    host_totals = sorted(
        (
            {
                "subject": subject,
                "total_bytes": sum(
                    int(rows.get(date, {}).get("total_bytes", 0)) for date in current_dates
                ),
            }
            for subject, rows in current_host.items()
        ),
        key=lambda item: int(item["total_bytes"]),
        reverse=True,
    )

    data = {
        "policy_version": POLICY_VERSION,
        "verdict": verdict,
        "window": {
            "start": window_start,
            "end": window_end,
            "days": window_days,
            "observed_through": freshness["observed_through"],
        },
        "baseline_window": {
            "start": baseline_start,
            "end": baseline_end,
            "requested_days": baseline_days,
        },
        "coverage": {
            "active_window_days": len(current_dates),
            "active_baseline_days": len(baseline_dates),
            "available_rollups": store.rollup_bounds(),
            **freshness,
            "process_attribution": {
                "status": "degraded" if attribution_degraded else "healthy",
                "known_bytes": current_process_total - unknown_total,
                "unknown_bytes": unknown_total,
                "unknown_ratio": round(unknown_ratio, 6),
                "minimum_unknown_bytes": min_unknown_bytes,
                "maximum_unknown_ratio": unknown_ratio_threshold,
            },
        },
        "summary": {
            "total_bytes": current_process_total,
            "unknown_bytes": unknown_total,
            "unknown_ratio": round(unknown_ratio, 6),
            "case_count": total_case_count,
            "returned_case_count": len(cases),
            "top_processes": process_totals[:10],
            "top_hosts": host_totals[:10],
        },
        "cases": [case.to_dict() for case in cases],
    }
    return data, warnings, next_actions


def find_case(store: LedgerStore, case_id: str, *, case_limit: int = 500) -> dict[str, Any]:
    identity = parse_case_id(case_id)
    data, _, _ = audit_traffic(
        store,
        identity["end_date"],
        window_days=identity["window_days"],
        baseline_days=identity["baseline_days"],
        case_limit=case_limit,
    )
    for case in data["cases"]:
        if case["case_id"] == case_id:
            return case
    raise LookupError(f"case is no longer present under the current policy: {case_id}")


def build_evidence(
    store: LedgerStore,
    case: dict[str, Any],
    *,
    limit: int = 20,
) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("evidence limit must be positive")
    subject_type = str(case["subject"]["type"])
    subject = str(case["subject"]["value"])
    window_start = str(case["window"]["start"])
    window_end = str(case["window"]["end"])
    baseline_days = int(parse_case_id(str(case["case_id"]))["baseline_days"])
    baseline_end = (Date.fromisoformat(window_start) - timedelta(days=1)).isoformat()
    baseline_start, _ = _date_window(baseline_end, baseline_days)

    series = store.subject_daily(subject_type, baseline_start, window_end, subject=subject)
    for row in series:
        row["phase"] = "window" if str(row["date"]) >= window_start else "baseline"

    breakdown = store.evidence_breakdown(
        subject_type,
        subject,
        window_start,
        window_end,
        limit=limit,
    )
    source_breakdown = store.evidence_source_breakdown(
        subject_type,
        subject,
        window_start,
        window_end,
        limit=limit,
    )
    connection_pattern = store.evidence_connection_pattern(
        subject_type,
        subject,
        window_start,
        window_end,
        limit=limit,
    )
    limitations = list(case.get("limitations") or [])
    raw_bounds = store.raw_bounds()
    if not breakdown:
        limitations.append("No retained raw delta rows are available for this case window.")
    elif raw_bounds["first_date"] and str(raw_bounds["first_date"]) > window_start:
        limitations.append("Raw evidence retention starts after the beginning of this case window.")

    return {
        "case": case,
        "daily_series": series,
        "top_counterparties": breakdown,
        "source_breakdown": source_breakdown,
        "connection_pattern": connection_pattern,
        "raw_evidence_bounds": raw_bounds,
        "limitations": list(dict.fromkeys(limitations)),
    }
