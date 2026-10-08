from __future__ import annotations

from html import escape
import json
from datetime import datetime, date as Date, timedelta
from .dashboard import panels, STYLE, query_options, to_csv
from .explore import explore
from .agent_api import capabilities, query_response
from .contracts import envelope, error_item, exception_response
from .overview import render_overview, render_details
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .anomalies import detect_anomalies
from .reports import human_bytes
from .status import LedgerStatus, build_status
from .store import LedgerStore


def _table(title: str, key: str, rows: list[dict[str, int | str]]) -> str:
    if not rows:
        return f"<section><h2>{escape(title)}</h2><p class=\"empty\">No data</p></section>"

    body = "\n".join(
        "<tr>"
        f"<td>{escape(str(row[key]))}</td>"
        f"<td>{human_bytes(int(row['upload_bytes']))}</td>"
        f"<td>{human_bytes(int(row['download_bytes']))}</td>"
        f"<td>{human_bytes(int(row['total_bytes']))}</td>"
        "</tr>"
        for row in rows
    )
    return (
        f"<section><h2>{escape(title)}</h2>"
        "<table><thead><tr>"
        f"<th>{escape(key)}</th><th>Upload</th><th>Download</th><th>Total</th>"
        "</tr></thead>"
        f"<tbody>{body}</tbody></table></section>"
    )


def _summary(status: LedgerStatus) -> str:
    latest = escape(status.latest_sample or "none")
    service_state = escape(status.service_state or "not checked")
    return (
        "<section class=\"summary\">"
        f"<div><span>Total</span><strong>{human_bytes(status.today_total_bytes)}</strong></div>"
        f"<div><span>Upload</span><strong>{human_bytes(status.today_upload_bytes)}</strong></div>"
        f"<div><span>Download</span><strong>{human_bytes(status.today_download_bytes)}</strong></div>"
        f"<div><span>Rows</span><strong>{status.raw_delta_rows}</strong></div>"
        f"<div><span>Service process</span><strong>{service_state}</strong></div>"
        f"<div><span>Latest traffic</span><strong>{latest}</strong></div>"
        "</section>"
    )


def _trend(rows: list[dict[str, int | str]]) -> str:
    peak = max((int(row["total_bytes"]) for row in rows), default=0)
    body = "\n".join(
        "<tr>"
        f"<td>{escape(str(row['date']))} · {escape(str(row.get('coverage','unknown')))}</td>"
        "<td><div class=\"bar-track\">"
        f"<span class=\"bar\" style=\"width: {0 if peak == 0 else int(int(row['total_bytes']) / peak * 100)}%\"></span>"
        "</div></td>"
        f"<td>{human_bytes(int(row['total_bytes'])) if int(row['total_bytes']) else '— 无流量记录'}</td>"
        "</tr>"
        for row in rows
    )
    return (
        "<section><h2>Daily trend</h2>"
        "<table><thead><tr><th>Date</th><th>Trend</th><th>Total</th></tr></thead>"
        f"<tbody>{body}</tbody></table></section>"
    )


def _anomaly_panel(store: LedgerStore, date: str, byte_threshold: int) -> str:
    anomalies = detect_anomalies(
        store,
        date,
        byte_threshold=byte_threshold,
        unknown_ratio_threshold=0.25,
        spike_multiplier=3.0,
    )
    if not anomalies:
        return "<section><h2>Anomaly hints</h2><p class=\"empty\">No anomaly hints</p></section>"
    items = "\n".join(
        f"<li><strong>{escape(item.code)}</strong>: {escape(item.message)}</li>" for item in anomalies
    )
    return f"<section><h2>Anomaly hints</h2><ul class=\"anomalies\">{items}</ul></section>"


def render_dashboard(
    store: LedgerStore,
    date: str,
    status: LedgerStatus | None = None,
    anomaly_byte_threshold: int = 500 * 1024 * 1024,
    options: dict | None = None,
) -> str:
    current_status = status or build_status(store, date, service_label=None)
    process_rows = store.daily_process(date, limit=20)
    host_rows = store.daily_host(date, limit=20)
    trend_rows = store.daily_totals(date, days=7)
    day_coverage = {d['date']: d['status'] for d in store.coverage((Date.fromisoformat(date)-timedelta(days=6)).isoformat(),date)['days']}
    for row in trend_rows:
        row['coverage'] = day_coverage[row['date']]
    options = options or dict(start=date,end=date,by='process',process='',host='',route='')
    detail = panels(store,options)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Clash Verge Traffic Ledger</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f8fa;
      --panel: #ffffff;
      --text: #17202a;
      --muted: #667085;
      --border: #d9dee7;
      --accent: #0f766e;
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 32px 20px 48px;
    }}
    header {{
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 24px;
    }}
    h1 {{
      margin: 0;
      font-size: 30px;
      line-height: 1.15;
    }}
    .date {{
      color: var(--muted);
      font-size: 14px;
      font-weight: 600;
    }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 10px;
      margin-bottom: 28px;
    }}
    .summary div, section {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
    }}
    .summary div {{
      padding: 14px;
    }}
    .summary span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 8px;
    }}
    .summary strong {{
      font-size: 18px;
    }}
    section {{
      margin-top: 16px;
      overflow: hidden;
    }}
    h2 {{
      margin: 0;
      padding: 14px 16px;
      font-size: 15px;
      border-bottom: 1px solid var(--border);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}
    th, td {{
      padding: 11px 16px;
      border-bottom: 1px solid var(--border);
      text-align: right;
      white-space: nowrap;
    }}
    th:first-child, td:first-child {{
      text-align: left;
      white-space: normal;
    }}
    th {{
      color: var(--muted);
      font-weight: 600;
    }}
    .empty {{
      margin: 0;
      padding: 16px;
      color: var(--muted);
    }}
    .bar-track {{
      height: 8px;
      min-width: 120px;
      background: #edf1f5;
      border-radius: 999px;
      overflow: hidden;
    }}
    .bar {{
      display: block;
      height: 100%;
      background: var(--accent);
    }}
    .anomalies {{
      margin: 0;
      padding: 12px 16px 16px 34px;
      color: var(--text);
      font-size: 14px;
    }}
    .anomalies li + li {{
      margin-top: 8px;
    }}
    @media (max-width: 640px) {{
      header {{
        align-items: start;
        flex-direction: column;
      }}
      main {{
        padding: 24px 12px 36px;
      }}
      th, td {{
        padding: 10px 8px;
      }}
    }}
    {STYLE}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Clash Verge Traffic Ledger</h1>
      <div class="date">{escape(date)}</div>
    </header>
    {detail}
    <details><summary>结束日期的全部接管流量与最近 7 日趋势（不随上方筛选改变）</summary>
    {_summary(current_status)}
    {_trend(trend_rows)}
    <section><h2>异常提示说明</h2><p>流量变化、应用归属缺口与采集故障分开解释。覆盖不完整时降低结论置信度；统计峰值不是恶意判定。使用上方异常证据入口查看基线和限制。</p></section>
    {_table("Traffic by process", "process", process_rows)}
    {_table("Traffic by host", "host", host_rows)}
    </details>
  </main>
</body>
</html>
"""


def serve_dashboard(store: LedgerStore, host: str, port: int) -> None:
    class Handler(BaseHTTPRequestHandler):
        def machine_error(self, status, code, message):
            body = json.dumps(envelope(urlparse(self.path).path.rsplit('/', 1)[-1], None,
                ok=False, errors=[error_item(code, message)])).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_error(self, code, message=None, explain=None):
            if urlparse(self.path).path.startswith('/api/'):
                return self.machine_error(code, {400:'invalid_request',403:'forbidden',404:'not_found',501:'method_not_allowed'}.get(code, 'resource_unavailable'), message or self.responses[code][0])
            return super().send_error(code, message, explain)

        def do_GET(self) -> None:
            # Loopback-only and Host/Origin validation prevent DNS rebinding reads.
            allowed = {f'127.0.0.1:{port}',f'localhost:{port}'}
            if self.headers.get('Host') not in allowed:
                self.send_error(403); return
            origin = self.headers.get('Origin')
            if origin and origin not in {f'http://{h}' for h in allowed}:
                self.send_error(403); return
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            try:
                date = query.get('date',[datetime.now().astimezone().date().isoformat()])[0]
                Date.fromisoformat(date)
                options = query_options(query,date)
                if parsed.path.startswith('/assets/'):
                    relative = parsed.path[len('/assets/'):]
                    asset_root = Path(__file__).parent / 'assets'
                    target = (asset_root / relative).resolve()
                    if not target.is_relative_to(asset_root.resolve()) or not target.is_file():
                        self.send_error(404); return
                    types={'.css':'text/css; charset=utf-8','.js':'text/javascript; charset=utf-8','.svg':'image/svg+xml'}
                    if target.suffix not in types:
                        self.send_error(404); return
                    body=target.read_bytes();mime=types[target.suffix]
                elif parsed.path in ('/','/index.html'):
                    view=query.get('view',['overview'])[0]
                    if view not in ('overview','history','details'):
                        raise ValueError('Unknown view')
                    # Validate legacy range parameters even when displaying the overview.
                    from .explore import validate_range
                    validate_range(options['start'], options['end'])
                    html=render_details(store,options['end'],options) if view=='details' else render_overview(store,options['end'],view,options['route'])
                    body = html.encode('utf-8')
                    mime = 'text/html; charset=utf-8'
                elif parsed.path == '/api/capabilities':
                    body = json.dumps(capabilities()).encode('utf-8')
                    mime = 'application/json'
                elif parsed.path in ('/api/explore','/export.csv'):
                    limit = int(query.get('limit',['50'])[0])
                    data = query_response('explore', store, **options, limit=limit)
                    body = (to_csv(data['data']) if parsed.path == '/export.csv' else json.dumps(data,ensure_ascii=False)).encode('utf-8')
                    mime = 'text/csv; charset=utf-8' if parsed.path == '/export.csv' else 'application/json'
                elif parsed.path == '/api/evidence':
                    data = query_response('evidence', store, case_id=query.get('case_id',[''])[0], limit=int(query.get('limit',['20'])[0]))
                    body = json.dumps(data,ensure_ascii=False).encode('utf-8')
                    mime = 'application/json'
                elif parsed.path == '/api/audit':
                    data = query_response('audit', store, end_date=query.get('end_date',[options['end']])[0],
                        window_days=int(query.get('since',['7'])[0]), baseline_days=int(query.get('baseline',['30'])[0]), case_limit=int(query.get('limit',['50'])[0]))
                    body = json.dumps(data,ensure_ascii=False).encode('utf-8')
                    mime = 'application/json'
                else:
                    self.send_error(404); return
            except Exception as exc:
                if parsed.path.startswith('/api/'):
                    result, code = exception_response(parsed.path.rsplit('/', 1)[-1], exc)
                    err = result['errors'][0]
                    self.machine_error(400 if code == 4 else 503 if code == 3 else 500, err['code'], err['message'])
                else:
                    self.send_error(400 if isinstance(exc, (ValueError, TypeError, LookupError)) else 503, 'Invalid request or unavailable ledger')
                return
            self.send_response(200)
            self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
            if parsed.path == '/export.csv':
                self.send_header('Content-Disposition','attachment; filename="traffic.csv"')
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    if host not in ('127.0.0.1','localhost'):
        raise ValueError('Dashboard only supports loopback access')
    with ThreadingHTTPServer((host, port), Handler) as server:
        server.serve_forever()
