"""Local dashboard panels shared by page rendering and drill-down endpoints."""

from datetime import datetime
from html import escape
from urllib.parse import urlencode
import csv
import io
from .explore import explore
from .reports import human_bytes
from .audit import audit_traffic

LABELS = {
    "process": "应用",
    "host": "域名",
    "route": "线路类型",
    "hour": "小时",
    "minute": "分钟",
    "connection": "连接",
    "rule": "匹配规则",
    "chain": "代理链",
}


def query_options(query, fallback):
    values = {
        k: query.get(k, [""])[0]
        for k in ("start", "end", "by", "process", "host", "route")
    }
    values["start"] = values["start"] or fallback
    values["end"] = values["end"] or fallback
    values["by"] = values["by"] or "process"
    values["sort"] = query.get("sort", ["total"])[0]
    values["offset"] = int(query.get("offset", ["0"])[0])
    return values


def to_csv(data):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        [
            "subject",
            "upload_bytes",
            "download_bytes",
            "total_bytes",
            "coverage_status",
            "source",
        ]
    )
    for r in data["rows"]:
        # Neutralize formula injection when opened in a spreadsheet.
        subject = str(r["subject"])
        if subject.startswith(("=", "+", "-", "@", "\t", "\r")):
            subject = "'" + subject
        writer.writerow(
            [
                subject,
                r["upload_bytes"],
                r["download_bytes"],
                r["total_bytes"],
                data["coverage"]["status"],
                data["source"],
            ]
        )
    return out.getvalue()


def panels(store, options):
    options = {"sort": "total", "offset": 0, **options}
    data = explore(store, **options, limit=100)
    state = store.sampling_state()
    now = datetime.now().astimezone()
    age = (
        (now - datetime.fromisoformat(state["last_success"])).total_seconds()
        if state.get("last_success")
        else None
    )
    healthy = state.get("status") == "ok" and age is not None and 0 <= age <= 180
    status = (
        "采样正常"
        if healthy
        else ("采样中断" if state else "无采样心跳 · 历史覆盖未知")
    )
    coverage = data["coverage"]
    coverage_label = {"complete": "完整", "partial": "部分覆盖", "unknown": "未知"}[
        coverage["status"]
    ]
    ratio = "—" if coverage["ratio"] is None else f"{coverage['ratio'] * 100:.1f}%"
    esc = lambda s: escape(str(s), quote=True)
    inputs = "".join(
        f'<label>{title}<input name="{key}" value="{esc(options[key])}" type="{typ}"></label>'
        for key, title, typ in [
            ("start", "开始日期", "date"),
            ("end", "结束日期", "date"),
            ("process", "应用（精确匹配）", "text"),
            ("host", "域名（精确匹配）", "text"),
        ]
    )
    groups = "".join(
        f'<option value="{key}" {"selected" if key == options["by"] else ""}>{title}</option>'
        for key, title in LABELS.items()
    )
    routes = "".join(
        f'<option value="{key}" {"selected" if key == options["route"] else ""}>{title}</option>'
        for key, title in [
            ("", "全部接管流量"),
            ("proxy", "代理"),
            ("direct", "DIRECT"),
            ("unknown", "线路未知"),
        ]
    )
    sorts = "".join(
        f'<option value="{k}" {"selected" if options["sort"] == k else ""}>{v}</option>'
        for k, v in [
            ("total", "总量优先"),
            ("upload", "上传优先"),
            ("download", "下载优先"),
            ("time", "时间 / 名称顺序"),
        ]
    )
    navigation = []
    for title, offset in [
        ("上一页", options["offset"] - 100),
        ("下一页", options["offset"] + 100),
    ]:
        if 0 <= offset < data["total_groups"]:
            navigation.append(
                f'<a href="/?{esc(urlencode({**options, "offset": offset}))}">{title}</a>'
            )
    page_links = " · ".join(navigation)
    table = []
    for r in data["rows"]:
        text = esc(r["subject"])
        if options["by"] in ("process", "host"):
            target = {
                **options,
                options["by"]: r["subject"],
                "by": "minute",
                "offset": 0,
            }
            text = f'<a href="/?{esc(urlencode(target))}">{text}</a>'
        details = ""
        if options["by"] == "connection":
            details = (
                "<br><small>"
                + esc(
                    " · ".join(
                        str(r.get(k, ""))
                        for k in (
                            "processes",
                            "hosts",
                            "rules",
                            "chains",
                            "first_seen",
                            "last_seen",
                        )
                    )
                )
                + "</small>"
            )
        table.append(
            f"<tr><td>{text}{details}</td><td>{human_bytes(r['upload_bytes'])}</td><td>{human_bytes(r['download_bytes'])}</td><td>{human_bytes(r['total_bytes'])}</td></tr>"
        )
    events = (
        "".join(
            f"<li>{esc(r['ts'])} · {esc(r['kind'])} · {esc(r['detail'])}</li>"
            for r in store.recent_events(10)
        )
        or "<li>没有可用事件；历史无心跳不能推断持续在线。</li>"
    )
    comparison = store.meter_comparison(options["start"], options["end"])
    meter = "尚无可比较的内核总计数样本"
    if comparison["status"] == "available":
        meter = f"可比较区间内：内核 {human_bytes(comparison['core_upload'] + comparison['core_download'])} / 连接账本 {human_bytes(comparison['recorded_upload'] + comparison['recorded_download'])}；差额 {human_bytes(comparison['unattributed_bytes'])}（短连接、首次基线等可能造成差异）"
    day_cells = "".join(
        f'<span title="{esc(d["date"])}：{esc(d["status"])}" class="day {d["status"]}">{esc(d["date"][5:])}</span>'
        for d in coverage["days"]
    )
    audit, warnings, _ = audit_traffic(store, options["end"], case_limit=8)
    case_rows = []
    for case in audit["cases"]:
        label = "归属缺口" if case["code"] == "unknown_process_ratio" else "流量变化"
        value = case["subject"]["value"]
        hint = (
            "更新下载域名；仍需结合当时操作确认。"
            if value
            in (
                "updates.cdn-apple.com",
                "downloads.cursor.com",
                "release-assets.githubusercontent.com",
            )
            else "需结合连接明细和当时操作解释。"
        )
        confidence_label = {"low": "低", "medium": "中", "high": "高"}[
            case["confidence"]
        ]
        case_rows.append(
            f'<li><strong>{esc(value)}</strong> · {label} · {human_bytes(case["observed_upload_bytes"] if "upload" in case["code"] else case["observed_bytes"])} · 置信度 {esc(confidence_label)}<br>{esc(case["code"])}；{hint} <a href="/api/evidence?case_id={esc(case["case_id"])}">连接证据</a></li>'
        )
    verdict_labels = {
        "anomalies_detected": "发现流量变化",
        "no_anomalies": "未触发规则",
        "insufficient_data": "证据不足",
    }
    audit_html = (
        "<section><h2>最近 7 天的变化线索</h2><p>结束日期 "
        + esc(options["end"])
        + " · "
        + esc(verdict_labels[audit["verdict"]])
        + " · 基线有效流量日 "
        + str(audit["coverage"]["active_baseline_days"])
        + "/30。此区域分析全部接管流量，不随应用筛选改变。</p><ul>"
        + (
            "".join(case_rows)
            or "<li>没有触发流量规则；覆盖不足时不能据此推断正常。</li>"
        )
        + "</ul></section>"
    )
    query = urlencode(options)
    return f"""<section class="health {"good" if healthy else "bad"}"><h2>{status}</h2>
    <p>最近成功采样：{esc(state.get("last_success") or "未知")}<br>最近尝试：{esc(state.get("last_attempt") or "未知")} · 错误：{esc(state.get("error") or "无")}</p>
    <p>所选范围：{coverage_label} · 已证实覆盖率 {ratio}。缺失时间不等于零流量；当天始终是未结束的一天。</p>
    <div class="days">{day_cells}</div></section>
    <section><h2>流量探索</h2><form>{inputs}<label>分组<select name="by">{groups}</select></label><label>统计口径<select name="route">{routes}</select></label><label>排序<select name="sort">{sorts}</select></label><button>查询</button><a href="/">重置</a></form>
    <p>筛选总量 <strong>{human_bytes(data["totals"]["total_bytes"])}</strong> · 上传 {human_bytes(data["totals"]["upload_bytes"])} · 下载 {human_bytes(data["totals"]["download_bytes"])} · {data["total_groups"]} 组</p>
    <p>明细保留状态：{esc({"complete": "完整", "partial": "部分缺失"}[data["retained_detail"]["status"]])}。点击应用或域名进入分钟明细，再切换“连接 / 匹配规则 / 代理链”。每页 100 组，可按上传或下载排序定位峰值；分钟和连接依赖仍保留的原始明细。</p>
    <div class="scroll"><table><thead><tr><th>{LABELS[options["by"]]}</th><th>上传</th><th>下载</th><th>总量</th></tr></thead><tbody>{"".join(table) or '<tr><td colspan="4">没有记录，不代表零流量</td></tr>'}</tbody></table></div>
    <p>{page_links} · 当前第 {options["offset"] // 100 + 1} 页</p><p><a href="/export.csv?{esc(query)}">导出当前页 CSV</a> · <a href="/api/explore?{esc(query)}">查看 JSON 与覆盖证据</a> · <a href="/api/audit?{esc(urlencode({"end": options["end"]}))}">最近 7 天异常证据</a></p></section>
    {audit_html}
    <section><h2>计量边界</h2><p>{meter}</p><p>Clash 接管总量包含 DIRECT。代理节点流量也不保证与服务端计费一致；不记录请求正文，不能据此确定上传了什么文件。</p></section>
    <section><h2>采集事件</h2><ul>{events}</ul></section>"""


STYLE = """
details {margin-top:20px}summary {cursor:pointer;padding:16px;color:#536174}

.health p,section>p {padding:0 16px;line-height:1.65;color:#536174}
.health.bad {border-left:4px solid #b7791f}.health.good {border-left:4px solid #0f766e}
form {display:flex;flex-wrap:wrap;gap:12px;padding:16px;align-items:end}
label {display:flex;flex-direction:column;gap:6px;font-size:12px;color:#536174}
input,select,button {font:inherit;padding:9px;border:1px solid #cbd5e1;border-radius:6px;background:white;color:#17202a}
button {background:#0f766e;color:white;cursor:pointer}a {color:#08766e}a:focus,button:focus,input:focus,select:focus {outline:2px solid #08766e;outline-offset:3px}
.scroll {overflow:auto}small {display:block;max-width:650px;overflow-wrap:anywhere;line-height:1.5;color:#536174}
.days {display:flex;flex-wrap:wrap;gap:4px;padding:0 16px 16px}.day {padding:5px;font-size:11px;border-radius:3px}
.day.unknown {background:#e5e7eb;color:#475569}.day.partial {background:#fef3c7;color:#92400e}.day.complete {background:#ccfbf1;color:#115e59}
section ul {line-height:1.8;overflow-wrap:anywhere;padding-right:16px}
"""
