from __future__ import annotations

from html import escape
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
        f"<div><span>Sampler</span><strong>{service_state}</strong></div>"
        f"<div><span>Latest sample</span><strong>{latest}</strong></div>"
        "</section>"
    )


def _trend(rows: list[dict[str, int | str]]) -> str:
    peak = max((int(row["total_bytes"]) for row in rows), default=0)
    body = "\n".join(
        "<tr>"
        f"<td>{escape(str(row['date']))}</td>"
        "<td><div class=\"bar-track\">"
        f"<span class=\"bar\" style=\"width: {0 if peak == 0 else int(int(row['total_bytes']) / peak * 100)}%\"></span>"
        "</div></td>"
        f"<td>{human_bytes(int(row['total_bytes']))}</td>"
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
) -> str:
    current_status = status or build_status(store, date)
    process_rows = store.daily_process(date, limit=20)
    host_rows = store.daily_host(date, limit=20)
    trend_rows = store.daily_totals(date, days=7)
    return f"""<!doctype html>
<html lang="en">
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
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Clash Verge Traffic Ledger</h1>
      <div class="date">{escape(date)}</div>
    </header>
    {_summary(current_status)}
    {_trend(trend_rows)}
    {_anomaly_panel(store, date, anomaly_byte_threshold)}
    {_table("Traffic by process", "process", process_rows)}
    {_table("Traffic by host", "host", host_rows)}
  </main>
</body>
</html>
"""


def serve_dashboard(store: LedgerStore, host: str, port: int) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path not in {"/", "/index.html"}:
                self.send_error(404)
                return
            query = parse_qs(parsed.query)
            date = query.get("date", [""])[0]
            if not date:
                from datetime import datetime

                date = datetime.now().astimezone().date().isoformat()
            body = render_dashboard(store, date).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    with ThreadingHTTPServer((host, port), Handler) as server:
        server.serve_forever()
