# clash-verge-traffic-ledger MVP Design

## Goal

Build a local Mihomo/Clash Verge traffic ledger that records future byte deltas and can answer:

- How much traffic was used today?
- Which apps/processes used the most traffic?
- Which hosts dominated usage?
- Is process attribution currently working on this Mac?

## Non-goals

- Reconstruct exact historical traffic from old logs.
- Replace MetaCubeXD/Yacd as a realtime dashboard.
- Ship a packaged macOS app in the first version.
- Require a remote service or paid dependency.

## Data source

Default controller:

- Unix socket: `/tmp/verge/verge-mihomo.sock`
- Endpoint: `GET /connections`

Optional controller:

- HTTP base URL such as `http://127.0.0.1:9090`
- Optional `Authorization: Bearer <secret>`

## Attribution

Process name priority:

1. `metadata.process`
2. Basename of `metadata.processPath`
3. `lsof` lookup by `metadata.sourcePort` when `metadata.sourceIP` is `127.0.0.1`
4. `unknown`

Host priority:

1. `metadata.host`
2. `metadata.destinationIP`
3. `unknown`

## Counting model

The monitor keeps the last seen upload/download counters for each Mihomo connection id.

- First observation of a connection establishes a baseline and records no delta.
- Later observations record positive counter increases.
- Negative deltas are treated as a counter reset and skipped.
- Missing connections are removed from the in-memory baseline.

This avoids a false spike when the monitor starts while long-lived connections already have bytes.

## Storage

SQLite tables:

- `traffic_deltas`: raw attributed byte deltas.
- `daily_process`: daily process rollups.
- `daily_host`: daily host rollups.

## CLI

- `doctor`: checks controller access, `/connections`, `lsof`, and current process coverage.
- `run`: starts polling and writing SQLite until interrupted.
- `today`: prints process and host rollups for the current date.
- `export`: writes Markdown or CSV for a chosen date.
- `status`: prints database status, sampler service state, latest sample time, raw row count, and daily totals.
- `anomalies`: prints high-usage, unknown-process-ratio, and process-spike hints.
- `web`: serves a local read-only dashboard with summary cards, 7-day trend, anomaly hints, process totals, and host totals.
- `prune`: deletes raw delta rows before a chosen date while preserving daily rollups.
- `compact`: compacts raw delta rows before a chosen date and reports preserved rollup dates.
- `install-service` / `uninstall-service`: writes and manages a per-user launchd sampler plist.

## Acceptance criteria

- Unit tests cover connection parsing, delta computation, `lsof` parsing, SQLite rollups, and report export.
- Unit tests cover service plist generation, service state parsing, status summaries, anomaly detection, Web dashboard rendering, and raw-detail compaction.
- `doctor` can query the current Clash Verge/Mihomo unix socket on this machine.
- A short live sampling run creates a SQLite database and readable `today`, `status`, `anomalies`, and Web dashboard output.
