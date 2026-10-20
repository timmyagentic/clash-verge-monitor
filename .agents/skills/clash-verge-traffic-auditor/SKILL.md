---
name: clash-verge-traffic-auditor
description: Audit and operate the local Clash Verge/Mihomo traffic ledger with deterministic evidence. Use when a user asks to install or start traffic monitoring, check sampler health, analyze recent or weekly abnormal traffic, identify high-traffic processes or hosts, investigate unknown process attribution, inspect an anomaly case, or safely plan data retention. Trigger for Chinese requests such as "分析最近一周异常流量", "谁用了最多代理流量", "unknown 为什么这么高", or "检查采样服务". This skill is macOS-first and does not use MCP or an embedded model.
---

# Clash Verge Traffic Auditor

Use the bundled scripts as the operational interface. Keep accounting and anomaly decisions in the deterministic Python runtime; use the host Agent only to choose the workflow, request confirmation, and explain evidence.

## Resolve The Runtime

Resolve paths relative to this loaded skill directory. Do not assume the current working directory.

```bash
python3 scripts/bootstrap.py status --pretty
python3 scripts/traffic_auditor.py capabilities --pretty
python3 scripts/traffic_auditor.py health --pretty
```

Treat `bootstrap.py status` as installation truth and `traffic_auditor.py health` as runtime truth. A degraded sampler can still have an audit-ready historical database.

`capabilities` reports the selected runtime version, supported commands, limits and
coverage/data enums. The wrapper prefers the installed runtime even when invoked
from a newer checkout. A legacy runtime returns `runtime_upgrade_required` for
new commands; it never silently switches to source or installs an upgrade.
To explicitly inspect a candidate, pass `--runtime-source <repo>` and
`--database <ledger.sqlite>` to each command. This selects source without changing
installation or service state. Read `runtime_selection` and `runtime.version` in
the response before attributing results to a candidate. With no source override,
`--runtime-python` selects an interpreter, not a source checkout.

## Install Or Start Monitoring

1. Run `bootstrap.py install --dry-run --source <repo>`.
2. Report the runtime, database, plist, and whether an existing database will be adopted.
3. Run the install only when the user requested installation.
4. Add `--load` only when the user requested monitoring to start or restart.
5. Run `status` and `health` after installation.

```bash
python3 scripts/bootstrap.py install --source <repo> --database <existing-ledger.sqlite> --dry-run --pretty
python3 scripts/bootstrap.py install --source <repo> --database <existing-ledger.sqlite> --load --pretty
```

Never move an existing database automatically. The stable runtime belongs under `~/Library/Application Support/clash-verge-traffic-ledger/`; LaunchAgents must not point into a mutable Skill cache or repository virtual environment.

## Audit Traffic

1. Run `health` first and record whether the database is readable, samples are fresh, and the controller is reachable.
2. Run a 7-day audit against a 30-day requested baseline unless the user names another window.
3. Read `verdict`, `coverage`, `summary`, and cases before drawing a conclusion.
4. Inspect evidence for the highest-severity relevant case. Do not expand every raw row.
5. Answer in the user's language with verdict, concrete byte evidence, baseline comparison, uncertainty, and the next safe check.

```bash
python3 scripts/traffic_auditor.py audit --since 7 --baseline 30 --pretty
python3 scripts/traffic_auditor.py evidence --case-id <case_id> --pretty
```

Use these interpretations:

- `anomalies_detected`: describe the cases and inspect evidence before assigning a cause.
- `no_anomalies`: say no configured deterministic rule fired; do not claim all traffic is safe.
- `insufficient_data`: state the active window and baseline coverage explicitly.
- `unknown_process_ratio`: describe an attribution gap, not malicious traffic.

Read [anomaly-policy.md](references/anomaly-policy.md) when explaining thresholds or confidence. Read [output-contract.md](references/output-contract.md) before changing script integration.

## Maintenance And Uninstall

Keep maintenance read-only until the user confirms a specific mutation. Show row counts and preserved rollups first. Prefer compaction when file-space recovery is required: it retains daily aggregates, deletes the selected raw evidence, and runs SQLite `VACUUM`.

```bash
python3 scripts/traffic_auditor.py maintain --before <YYYY-MM-DD> --mode compact --dry-run --pretty
python3 scripts/traffic_auditor.py maintain --before <YYYY-MM-DD> --mode compact --apply --pretty
```

Run uninstall without `--apply` first. It preserves data and logs even when applied.

```bash
python3 scripts/bootstrap.py uninstall --pretty
python3 scripts/bootstrap.py uninstall --apply --pretty
```

## Safety Rules

- Never modify Clash rules, close connections, block a process, or delete ledger data automatically.
- Never put a controller secret in shell history, plist arguments, logs, or JSON. Use `MIHOMO_SECRET` interactively or a mode-600 secret file for services.
- Never treat high traffic alone as malicious behavior.
- Never claim historical `unknown` traffic can be retroactively attributed.
- Never create a new empty database while answering an audit request; audit uses SQLite read-only mode.
- Stop and report the evidence after repeated lock, controller, or runtime failures. Consult [troubleshooting.md](references/troubleshooting.md) before retrying.

## Completion Evidence

For installation, return the stable runtime path, adopted database path, both service states, and health status. For audits, return the requested window, active baseline days, exact cases inspected, evidence limitations, and a concise conclusion. Do not expose the full raw JSON unless the user asks for it.

## Reliability (0.3.1 and later)

Use `--controller auto` for current-user socket discovery; an explicit endpoint stays pinned.
Health now uses successful sampling heartbeats, including idle polls. Legacy traffic timestamps
cannot establish coverage. Policy v3 lowers confidence for partial/unknown coverage; do not
reinterpret v2 case IDs as v3 cases. Re-run audit to obtain the current ID.

For filtered drill-down use the bundled wrapper:

```bash
python3 scripts/traffic_auditor.py explore --start 2026-08-22 --end 2026-08-22 --by process --route proxy --limit 50 --offset 0 --pretty
```

Group by process, host, route, hour, minute, connection, rule or chain. Filters
`--process`, `--host`, `--route` are exact matches. Sort by total/upload/download/time.
Advance offset by limit while `truncated` is true. Pages read live data and are not
an immutable snapshot. Consult `query`, `provenance`, `coverage`, `data_status`,
`retained_detail`, warnings and limitations together. `unobserved` and
`indeterminate_zero` never justify saying no traffic occurred; `observed_zero`
means zero retained sampled bytes with complete sampling coverage, not proof that
polling captured every short connection. `observed_nonzero` also requires checking
coverage before calling a total complete.
`backup`, `restore`, `retention`, and `migrate` provide maintenance workflows. Restore always
requires a new destination; restore, retention, migration and bootstrap rollback default to
preview. Use the explicit apply/load flags only within the user's authorized maintenance scope.
See the repository `docs/reliability.md` for the complete upgrade/rollback and measurement limits.
