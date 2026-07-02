# clash-verge-traffic-ledger

Local traffic ledger for Clash Verge Rev, with support for any Mihomo-compatible controller.

The MVP records future traffic from the Mihomo controller, attributes bytes to a process where possible, stores the data in SQLite, and prints daily reports from the local database.

## Why this project exists

Clash Verge/Mihomo logs are useful for connection history, but they usually do not preserve exact historical per-connection byte deltas. `clash-verge-traffic-ledger` records those deltas while the core is running, so daily app-level usage can be reconstructed later.

## References

This repo intentionally keeps the first version small and local. It borrows proven ideas from:

- [MetaCubeX/metacubexd](https://github.com/MetaCubeX/metacubexd): official Mihomo dashboard patterns for `/connections`, `/traffic`, and controller interactions.
- [haishanh/yacd](https://github.com/haishanh/yacd): high-star Clash dashboard UI and connection-list behavior.
- [foru17/neko-master](https://github.com/foru17/neko-master): heavier analytics approach with buffered connection ingestion.
- [zhf883680/clash-traffic-monitor](https://github.com/zhf883680/clash-traffic-monitor): SQLite/minute-bucket traffic monitor model.
- [Mooouy/clash-traffic-monitor](https://github.com/Mooouy/clash-traffic-monitor): small Python per-process monitor using `/connections`.
- [xth1227/Clash-Traffic-Bar](https://github.com/xth1227/Clash-Traffic-Bar): macOS menu bar patterns for Clash Verge unix-socket access and `lsof` fallback attribution.

## MVP

- Connect to Clash Verge Rev through the default unix socket: `/tmp/verge/verge-mihomo.sock`.
- Optionally connect to an HTTP controller for non-Verge Mihomo setups.
- Poll `/connections` at a configurable interval.
- Compute byte deltas per Mihomo connection id.
- Treat first-seen connections as a baseline, so old bytes are not counted as new monitor usage.
- Attribute process from Mihomo metadata first, then use an `lsof` fallback for localhost proxy connections.
- Store raw deltas and daily rollups in SQLite.
- Provide CLI commands for `doctor`, `run`, `today`, and `export`.

## Quick start

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python -m clash_verge_traffic_ledger doctor
python -m clash_verge_traffic_ledger run --interval 1
python -m clash_verge_traffic_ledger today
```

By default the database is created at `data/ledger.sqlite` under the current working directory.

## Commands

```bash
python -m clash_verge_traffic_ledger doctor
python -m clash_verge_traffic_ledger run --interval 1 --database data/ledger.sqlite
python -m clash_verge_traffic_ledger today --database data/ledger.sqlite
python -m clash_verge_traffic_ledger export --date 2026-07-02 --format markdown --output report.md
python -m clash_verge_traffic_ledger export --date 2026-07-02 --format csv --output report.csv
```

For HTTP controller mode:

```bash
python -m clash_verge_traffic_ledger doctor --controller http://127.0.0.1:9090 --secret "$MIHOMO_SECRET"
```

## Limits

- This records future traffic only. It cannot recover exact bytes from old Clash Verge logs that lack byte counters.
- Process attribution depends on Mihomo process metadata and `lsof`; TUN traffic without process metadata may remain `unknown`.
- The MVP is a CLI/local SQLite tool. A Web UI can be added after the accounting model is proven.
