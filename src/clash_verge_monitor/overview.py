"""Dashboard presentation over the existing read-only ledger queries."""

from datetime import date as Date, datetime, timedelta
from html import escape
import json
from urllib.parse import urlencode

from .explore import explore, validate_range
from .reports import human_bytes


def icon(name: str, css: str = "") -> str:
    return f'<img class="icon {css}" src="/assets/icons/{name}.svg" alt="" width="22" height="22">'


def link(date: str, view: str = "overview", **filters) -> str:
    return "/?" + escape(urlencode(dict(date=date, view=view, **filters)), quote=True)


def overview_data(store, date: str, view: str = "overview", route: str = "") -> dict:
    end = Date.fromisoformat(date)
    start = (end - timedelta(days=6)).isoformat() if view == "history" else date
    validate_range(start, date)
    apps = explore(store, start, date, by="process", route=route, limit=4)
    hosts = explore(store, start, date, by="host", route=route, limit=4)
    hourly = explore(
        store, start, date, by="hour", route=route, sort="time", limit=1000
    )
    # Unfiltered daily totals remain authoritative even if old detail was compacted.
    total = dict(apps["totals"])
    if not route:
        daily = store.subject_daily("process", start, date)
        total = {
            k: sum(int(r[k]) for r in daily)
            for k in ("upload_bytes", "download_bytes", "total_bytes")
        }
    buckets = {}
    for r in hourly["rows"]:
        key = r["subject"][:10] if view == "history" else r["subject"][11:13]
        row = buckets.setdefault(key, {"upload": 0, "download": 0})
        row["upload"] += r["upload_bytes"]
        row["download"] += r["download_bytes"]
    keys = (
        [(end - timedelta(days=6 - i)).isoformat() for i in range(7)]
        if view == "history"
        else [f"{h:02}" for h in range(24)]
    )
    state = store.sampling_state()
    latest = state.get("last_success") or store.latest_delta_timestamp()
    age = (
        (
            datetime.now().astimezone() - datetime.fromisoformat(state["last_success"])
        ).total_seconds()
        if state.get("last_success")
        else None
    )
    healthy = state.get("status") == "ok" and age is not None and 0 <= age <= 180
    status = "正在采集" if healthy else ("采集已中断" if state else "暂无实时采样")
    return dict(
        start=start,
        end=date,
        view=view,
        route=route,
        total=total,
        apps=apps["rows"],
        hosts=hosts["rows"],
        keys=keys,
        labels=[k[5:] if view == "history" else k + ":00" for k in keys],
        upload=[buckets.get(k, {}).get("upload") for k in keys],
        download=[buckets.get(k, {}).get("download") for k in keys],
        coverage=apps["coverage"],
        retained_detail=apps["retained_detail"],
        healthy=healthy,
        status=status,
        latest=latest,
        state=state,
    )


def number(value: int) -> str:
    amount, unit = human_bytes(value).rsplit(" ", 1)
    return f"{amount}<span>{unit}</span>"


def ranking(rows: list, total: int, date: str, by: str, route: str, start: str) -> str:
    if not rows:
        return '<div class="empty-list">此范围暂无流量记录</div>'
    out = []
    for row in rows:
        name = row["subject"]
        ratio = row["total_bytes"] / total * 100 if total else 0
        symbol = "world"
        if by == "process":
            symbol = {
                "codex": "terminal-2",
                "gh": "brand-github",
                "EdgeUpdater": "brand-edge",
            }.get(name, "layout-grid")
        url = link(
            date,
            "details",
            start=start,
            end=date,
            by="minute",
            route=route,
            **{by: name},
        )
        meter = (
            f'<meter min="0" max="100" value="{ratio:.2f}" aria-label="{escape(name)} 占比 {ratio:.1f}%"></meter>'
            if by == "process"
            else ""
        )
        out.append(
            f'<a class="rank-row {by}" href="{url}"><span class="subject">{icon(symbol)}<span title="{escape(name, quote=True)}">{escape(name)}</span></span>{meter}<span class="rank-value">{human_bytes(row["total_bytes"])}</span><span class="share">{ratio:.1f}%</span></a>'
        )
    return "".join(out)


def shell(date: str, view: str, main: str) -> str:
    nav = "".join(
        f'<a href="{link(date, target, **params)}" aria-label="{title}" class="nav-item {"selected" if view == active else ""}" {"aria-current=page" if view == active else ""}>{icon(symbol)}<span>{title}</span></a>'
        for target, active, title, symbol, params in [
            ("overview", "overview", "流量概览", "chart-bar", {}),
            ("details", "details", "应用程序", "layout-grid", {"by": "process"}),
            ("history", "history", "历史记录", "clock", {}),
        ]
    )
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Clash Verge Monitor · 流量概览</title><link rel="stylesheet" href="/assets/dashboard.css"><script src="/assets/chart.umd.js" defer></script><script src="/assets/dashboard.js" defer></script></head>
    <body><a class="skip" href="#main">跳到主要内容</a><aside class="sidebar"><a class="brand" aria-label="Clash Verge Monitor" href="{link(date)}"><span class="brand-mark">{icon("wave-sine")}</span><span>Clash Verge Monitor<small>本机流量账本</small></span></a><nav aria-label="主导航">{nav}</nav><div class="sidebar-note">让连接更清晰<small>Quietly observe,<br>better internet.</small></div></aside><main id="main">{main}</main></body></html>'''


def render_overview(store, date: str, view: str = "overview", route: str = "") -> str:
    data = overview_data(store, date, view, route)
    end = Date.fromisoformat(date)
    today = datetime.now().astimezone().date()
    latest = data["latest"]
    latest_label = latest[5:10].replace("-", "/") if latest else "暂无记录"
    status_class = "healthy" if data["healthy"] else "stale"
    title = "历史记录" if view == "history" else "流量概览"
    badge = "历史数据" if end < today else "今日"
    timecontrols = f'<form class="date-form"><input type="hidden" name="view" value="{view}"><input type="hidden" name="route" value="{escape(route)}"><label class="date-control">{icon("calendar")}<input aria-label="选择日期" type="date" name="date" value="{date}" max="{today.isoformat()}"></label><button class="date-submit" type="submit">查看</button></form>'
    header = f'<header class="top"><div><div class="title-row"><h1>{title}</h1><span class="badge">{badge}</span></div><p>查看流量使用趋势与应用分布</p></div><div class="top-right"><span class="today">{today.strftime("%Y-%m-%d")} · 本机时区</span>{timecontrols}<a class="state {status_class}" href="#collection">{icon("circle-check" if data["healthy"] else "alert-circle")}<span>{data["status"]} · 最后记录 {latest_label}</span></a></div></header>'
    metric_value = lambda key: (
        number(data["total"][key])
        if data["total"]["total_bytes"] or data["coverage"]["status"] != "unknown"
        else "—<span class=unknown-unit>暂无记录</span>"
    )
    metrics = (
        '<section class="metrics" aria-label="流量总览">'
        + "".join(
            f'<div class="metric {style}"><span class="metric-label">{label} {icon(symbol) if symbol else ""}</span><strong>{metric_value(key)}</strong></div>'
            for key, label, style, symbol in [
                ("total_bytes", "总流量", "total", ""),
                ("upload_bytes", "上传流量", "upload", "arrow-up"),
                ("download_bytes", "下载流量", "download", "arrow-down"),
            ]
        )
        + "</section>"
    )
    series = json.dumps(
        {k: data[k] for k in ["labels", "upload", "download"]}, ensure_ascii=False
    )
    series = escape(series, quote=True)
    chart_title = "近 7 天流量趋势" if view == "history" else "24 小时流量趋势"
    detail_url = link(
        date, "details", start=data["start"], end=date, by="minute", route=route
    )
    route_controls = "".join(
        f'<a class="route-chip {"active" if route == r else ""}" href="{link(date, view, route=r)}">{name}</a>'
        for r, name in [("", "全部"), ("proxy", "代理"), ("direct", "直连")]
    )
    chart = f'<section class="chart-section"><div class="section-heading"><h2>{chart_title}</h2><div class="chart-actions"><div class="route-switch" aria-label="流量口径">{route_controls}</div><div class="legend"><span class="upload">上传</span><span class="download">下载</span></div><a class="button" href="{detail_url}">查看明细 {icon("arrow-right")}</a></div></div><div class="chart-wrap"><canvas id="traffic-chart" data-series="{series}" role="img" aria-label="{chart_title}，上传和下载；缺失时段不按零流量绘制">可通过查看明细获取图表数据</canvas><p class="chart-empty" {"hidden" if any(v is not None for v in data["upload"]) else ""}>所选日期没有流量记录<span>试试其他日期；未采集不等于零流量。</span></p></div></section>'
    sections = []
    for by, label, rows in [
        ("process", "应用流量排行", data["apps"]),
        ("host", "流量目的地", data["hosts"]),
    ]:
        url = link(date, "details", start=data["start"], end=date, by=by, route=route)
        sections.append(
            f'<section class="ranking {by}"><div class="section-heading"><h2>{label}</h2><a class="text-link" href="{url}">查看全部 {icon("arrow-right")}</a></div><div class="rank-head"><span>{"应用" if by == "process" else "目的地"}</span><span>流量</span><span>占比</span></div>{ranking(rows, data["total"]["total_bytes"], date, by, route, data["start"])}</section>'
        )
    coverage = {
        "unknown": "历史覆盖未知",
        "partial": "部分时段有采样记录",
        "complete": "采样覆盖完整",
    }[data["coverage"]["status"]]
    collection = f'<details id="collection" class="collection"><summary>{icon("chevron-down")}<span>采集详情</span><small>{coverage}</small></summary><div class="collection-body"><p>最近流量：{escape(latest or "暂无")}。{coverage}；没有心跳的历史时段无法确认是否持续采集。</p><p>统计包含 Clash 接管的流量，代理与直连可单独查看。连接轮询可能漏计短连接，结果不等同服务端账单。</p><p>明细保留：{"完整" if data["retained_detail"]["status"] == "complete" else "部分缺失"}。<a href="/api/audit?end={date}">查看最近 7 天审计证据</a></p></div></details>'
    return shell(
        date,
        view,
        header
        + metrics
        + chart
        + '<div class="rankings">'
        + "".join(sections)
        + "</div>"
        + collection,
    )


def readable_chains(value: str) -> str:
    decoder = json.JSONDecoder()
    groups = []
    remaining = value.strip()
    try:
        while remaining:
            chain, end = decoder.raw_decode(remaining)
            groups.append(
                " → ".join(str(x) for x in chain)
                if isinstance(chain, list)
                else str(chain)
            )
            remaining = remaining[end:].lstrip(", ")
        return " / ".join(groups)
    except (ValueError, TypeError):
        return value


def render_details(store, date: str, options: dict) -> str:
    options = {"sort": "total", "offset": 0, **options}
    data = explore(store, **options, limit=50)
    labels = {
        "process": "应用",
        "host": "域名",
        "route": "线路",
        "hour": "小时",
        "minute": "分钟",
        "connection": "连接",
        "rule": "规则",
        "chain": "代理链",
    }
    esc = lambda x: escape(str(x), quote=True)
    fields = "".join(
        f'<label>{label}<input name="{k}" type="{typ}" value="{esc(options[k])}"></label>'
        for k, label, typ in [
            ("start", "开始日期", "date"),
            ("end", "结束日期", "date"),
            ("process", "应用", "text"),
            ("host", "域名", "text"),
        ]
    )
    for key, label, choices in [
        ("by", "分组", list(labels.items())),
        (
            "sort",
            "排序",
            [
                ("total", "总量优先"),
                ("upload", "上传优先"),
                ("download", "下载优先"),
                ("time", "时间 / 名称"),
            ],
        ),
        (
            "route",
            "线路",
            [("", "全部"), ("proxy", "代理"), ("direct", "直连"), ("unknown", "未知")],
        ),
    ]:
        fields += (
            f'<label>{label}<select name="{key}">'
            + "".join(
                f'<option value="{k}" {"selected" if options[key] == k else ""}>{v}</option>'
                for k, v in choices
            )
            + "</select></label>"
        )
    rows = []
    for r in data["rows"]:
        name = esc(r["subject"])
        if options["by"] in ("process", "host"):
            target = {
                **options,
                options["by"]: r["subject"],
                "by": "minute",
                "offset": 0,
            }
            name = f'<a href="{link(date, "details", **target)}">{name}</a>'
        extra = ""
        if options["by"] == "connection":
            extra = (
                "<small>"
                + esc(
                    " · ".join(
                        (
                            readable_chains(str(r.get(k, "")))
                            if k == "chains"
                            else str(r.get(k, ""))
                        )
                        for k in [
                            "processes",
                            "hosts",
                            "rules",
                            "chains",
                            "first_seen",
                            "last_seen",
                        ]
                    )
                )
                + "</small>"
            )
        rows.append(
            f"<tr><td>{name}{extra}</td><td>{human_bytes(r['upload_bytes'])}</td><td>{human_bytes(r['download_bytes'])}</td><td>{human_bytes(r['total_bytes'])}</td></tr>"
        )
    pager = "".join(
        f'<a class="text-link" href="{link(date, "details", **{**options, "offset": offset})}">{title}</a>'
        for title, offset in [
            ("上一页", options["offset"] - 50),
            ("下一页", options["offset"] + 50),
        ]
        if 0 <= offset < data["total_groups"]
    )
    export = escape("/export.csv?" + urlencode({**options, "limit": 50}), quote=True)
    main = f'<header class="top"><div><div class="title-row"><h1>流量明细</h1></div><p><a class="text-link" href="{link(date)}">返回流量概览</a> · {esc(options["start"])} 至 {esc(options["end"])}</p></div><a class="button secondary" href="{export}">导出当前页 CSV</a></header><form class="filters"><input type="hidden" name="view" value="details">{fields}<button class="button">查询</button><a class="text-link" href="{link(date, "details")}">重置</a></form><div class="detail-summary"><strong>{human_bytes(data["totals"]["total_bytes"])}</strong><span>上传 {human_bytes(data["totals"]["upload_bytes"])} · 下载 {human_bytes(data["totals"]["download_bytes"])} · {data["total_groups"]} 组</span></div><div class="detail-table"><table><thead><tr><th>{labels[options["by"]]}</th><th>上传</th><th>下载</th><th>总量</th></tr></thead><tbody>{"".join(rows) or "<tr><td colspan=4>此范围没有流量记录</td></tr>"}</tbody></table></div><footer class="pager"><span>第 {options["offset"] // 50 + 1} 页 · 每页 50 组</span>{pager}</footer><p class="detail-note">{"历史覆盖未知" if data["coverage"]["status"] == "unknown" else "采样覆盖：" + data["coverage"]["status"]} · 明细{"完整" if data["retained_detail"]["status"] == "complete" else "部分缺失"}。未采集的时段不等于零流量。</p>'
    return shell(date, "details", main)
