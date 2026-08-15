# clash-verge-traffic-ledger

Local, Agent-native traffic auditor for Clash Verge Rev, with support for any Mihomo-compatible controller.

The runtime records future traffic from the Mihomo controller, attributes bytes to a process where possible, stores the data in SQLite, and exposes deterministic health, audit, evidence, reporting, and retention commands. The bundled Skill turns those commands into a natural-language workflow without MCP or a separate model API.

For the full Chinese project context and current MVP status, see [docs/project-brief.zh-CN.md](docs/project-brief.zh-CN.md).

## Release status

The current release line is `0.3.0`, which packages the policy-v2 auditor
hardening. Formal artifacts belong to the immutable
[`v0.3.0` GitHub Release](https://github.com/timmyagentic/clash-verge-traffic-ledger/releases/tag/v0.3.0).
A version in source or a local installation alone is not publication proof; see
[CHANGELOG.md](CHANGELOG.md) for the release notes and
[docs/releasing.md](docs/releasing.md) for the clean-source, build, publication,
download, and deployment verification gates.

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
- Attribute process from Mihomo metadata first, then capture at most one TCP/UDP `lsof` socket table after each controller snapshot that still needs localhost or TUN fallback attribution.
- Store raw deltas and daily rollups in SQLite.
- Provide CLI commands for `doctor`, `run`, `today`, and `export`.
- Install or remove a per-user `launchd` sampler service.
- Print database, sampler, and attribution health; expose deterministic anomaly and evidence output; provide a read-only local Web dashboard; and prune or compact old raw deltas.

## Agent-first Skill

The canonical Skill is
`.agents/skills/clash-verge-traffic-auditor/`. From Codex, invoke it with requests
such as "analyze the last week of Clash Verge traffic", "why is unknown traffic
high?", or "install and start monitoring".

The bundled bootstrap installs a versioned runtime under
`~/Library/Application Support/clash-verge-traffic-ledger/`. It adopts an
existing database by path and never moves it automatically.

```bash
python3 .agents/skills/clash-verge-traffic-auditor/scripts/bootstrap.py status --pretty
python3 .agents/skills/clash-verge-traffic-auditor/scripts/bootstrap.py install --source "$PWD" --dry-run --pretty
python3 .agents/skills/clash-verge-traffic-auditor/scripts/bootstrap.py install --source "$PWD" --load --pretty
python3 .agents/skills/clash-verge-traffic-auditor/scripts/traffic_auditor.py audit --since 7 --baseline 30 --pretty
```

Installation is idempotent. `--load` is explicit because it replaces and
restarts the per-user sampler and dashboard LaunchAgents. Uninstall and data
maintenance also default to a dry run.

The repository release and the locally installed runtime are separate states.
Use `bootstrap.py status` to inspect the installed version and provenance; only
deploy from a clean tagged checkout after the release artifacts are verified.

## Developer quick start

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
python -m clash_verge_traffic_ledger status --database data/ledger.sqlite
python -m clash_verge_traffic_ledger anomalies --database data/ledger.sqlite
python -m clash_verge_traffic_ledger health --database data/ledger.sqlite --pretty
python -m clash_verge_traffic_ledger audit --database data/ledger.sqlite --since 7 --baseline 30 --pretty
python -m clash_verge_traffic_ledger evidence --database data/ledger.sqlite --case-id CASE_ID --pretty
python -m clash_verge_traffic_ledger maintenance --database data/ledger.sqlite --before 2026-07-01 --dry-run --pretty
python -m clash_verge_traffic_ledger web --database data/ledger.sqlite --port 8765
python -m clash_verge_traffic_ledger prune --database data/ledger.sqlite --before 2026-07-01 --dry-run
python -m clash_verge_traffic_ledger compact --database data/ledger.sqlite --before 2026-07-01 --dry-run
```

Every raw-retention command defaults to a preview. It mutates the ledger only
when the same reviewed cutoff is rerun with `--apply`.

For HTTP controller mode:

```bash
python -m clash_verge_traffic_ledger doctor --controller http://127.0.0.1:9090 --secret "$MIHOMO_SECRET"
```

To install a login-time sampler on macOS:

```bash
python -m clash_verge_traffic_ledger install-service --database data/ledger.sqlite --interval 1
python -m clash_verge_traffic_ledger uninstall-service
```

Use `--no-load` to write the LaunchAgent plist without starting it immediately.
`status` checks the default service label with read-only `launchctl print`; pass
`--no-service-check` to report database-only status.

For persistent HTTP-controller authentication, use a mode-600 `--secret-file`.
Plain `--secret` values are intentionally rejected by `install-service` so they
cannot be written into plist arguments.

## Limits

- This records future traffic only. It cannot recover exact bytes from old Clash Verge logs that lack byte counters.
- Process attribution depends on Mihomo metadata and visible local TCP/UDP sockets. Ambiguous endpoints or sockets that disappear before sampling may remain `unknown`; health and audit output report that coverage gap explicitly.
- Current-day audit windows are partial and report their exact latest sample. An `unknown_process_ratio` is a coverage diagnostic, not proof of unwanted traffic.
- Applied compaction deletes raw drill-down history before the chosen cutoff, preserves daily rollups, and runs SQLite `VACUUM` to reclaim file space.
- The Web UI is intentionally read-only and local. It shows summary cards, a 7-day trend, anomaly hints, process totals, and host totals. The authoritative data remains in SQLite.
- Anomaly cases are deterministic evidence, not malware verdicts. High volume and `unknown` attribution require contextual review.
