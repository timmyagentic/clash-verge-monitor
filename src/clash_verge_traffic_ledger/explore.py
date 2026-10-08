"""Read-only, bounded drill-down; all SQL identifiers are selected from allowlists."""

from contextlib import closing
from datetime import date, timedelta
from .telemetry import ROUTE_SQL


def validate_range(start, end):
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first > last or (last - first).days > 366:
        raise ValueError("Choose a range of 1–367 days")
    return (last + timedelta(days=1)).isoformat()


def explore(
    store,
    start,
    end,
    *,
    by="process",
    process="",
    host="",
    route="",
    limit=50,
    offset=0,
    sort="total",
):
    stop = validate_range(start, end)
    if not 0 <= offset <= 1000000:
        raise ValueError("Offset must be between 0 and 1000000")
    order = {
        "time": "subject ASC",
        "total": "total_bytes DESC,subject ASC",
        "upload": "upload_bytes DESC,subject ASC",
        "download": "download_bytes DESC,subject ASC",
    }.get(sort)
    if order is None:
        raise ValueError("Unknown sort order")
    if route not in ("", "proxy", "direct", "unknown"):
        raise ValueError("Unknown route category")
    if by not in (
        "process",
        "host",
        "route",
        "hour",
        "minute",
        "connection",
        "rule",
        "chain",
    ):
        raise ValueError("Unknown grouping")
    if not 1 <= limit <= 1000:
        raise ValueError("Limit must be between 1 and 1000")
    hourly = store.has_table("hourly_traffic") and by in (
        "process",
        "host",
        "route",
        "hour",
    )
    source = (
        "hourly_traffic"
        if hourly
        else f"(SELECT *,{ROUTE_SQL} route FROM traffic_deltas)"
    )
    time_col = "hour" if hourly else "date"
    conditions, params = [f"{time_col}>=?", f"{time_col}<?"], [start, stop]
    for key, value in [("process", process), ("host", host), ("route", route)]:
        if value:
            conditions.append(f"{key}=?")
            params.append(value)
    key = {
        "minute": "substr(ts,1,16)",
        "connection": "connection_id",
        "hour": "hour" if hourly else "substr(ts,1,13)",
        "chain": "chains_json",
    }.get(by, by)
    extra = (
        ""
        if hourly
        else ",min(ts) first_seen,max(ts) last_seen,count(distinct connection_id) connections"
    )
    if by == "connection":
        # IDs occasionally change attribution; show every distinct recorded label.
        extra += ",group_concat(distinct process) processes,group_concat(distinct host) hosts,group_concat(distinct rule) rules,group_concat(distinct chains_json) chains"
    with closing(store.connect()) as c:
        base = f"FROM {source} WHERE {' AND '.join(conditions)}"
        rows = [
            dict(r)
            for r in c.execute(
                f"""SELECT {key} subject,sum(upload_bytes) upload_bytes,
            sum(download_bytes) download_bytes,sum(upload_bytes+download_bytes) total_bytes{extra}
            {base} GROUP BY {key} ORDER BY {order} LIMIT ? OFFSET ?""",
                params + [limit, offset],
            )
        ]
        totals = dict(
            c.execute(
                f"""SELECT coalesce(sum(upload_bytes),0) upload_bytes,
            coalesce(sum(download_bytes),0) download_bytes,
            coalesce(sum(upload_bytes+download_bytes),0) total_bytes {base}""",
                params,
            ).fetchone()
        )
        count = c.execute(
            f"SELECT count(*) FROM (SELECT {key} {base} GROUP BY {key})", params
        ).fetchone()[0]
    with closing(store.connect()) as c:
        full_total = c.execute(
            "SELECT coalesce(sum(upload_bytes+download_bytes),0) FROM daily_process WHERE date>=? AND date<?",
            (start, stop),
        ).fetchone()[0]
        if hourly:
            detail_total = c.execute(
                "SELECT coalesce(sum(upload_bytes+download_bytes),0) FROM hourly_traffic WHERE hour>=? AND hour<?",
                (start, stop),
            ).fetchone()[0]
        else:
            detail_total = c.execute(
                "SELECT coalesce(sum(upload_bytes+download_bytes),0) FROM traffic_deltas WHERE date>=? AND date<?",
                (start, stop),
            ).fetchone()[0]
    return {
        "retained_detail": {
            "status": "complete" if full_total == detail_total else "partial",
            "unfiltered_daily_bytes": full_total,
            "unfiltered_detail_bytes": detail_total,
        },
        "start": start,
        "end": end,
        "by": by,
        "rows": rows,
        "totals": totals,
        "total_groups": count,
        "truncated": count > offset + limit,
        "offset": offset,
        "limit": limit,
        "sort": sort,
        "source": "hourly" if hourly else "raw",
        "coverage": store.coverage(start, end),
        "limitations": [
            "Sampled connection deltas; short connections and first observations may be missed.",
            "Minute, connection, rule and chain detail can be absent after raw retention.",
            "Totals include DIRECT unless filtered; they are not provider billing.",
        ],
    }
