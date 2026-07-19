# Skill-first Auditor Verification

Date: 2026-07-19 (Asia/Shanghai)

## Scope

This run verifies the `clash-verge-traffic-auditor` Skill, deterministic JSON runtime, stable bootstrap, and read-only analysis against the existing local ledger. Live traffic values are snapshots, not permanent project facts.

## Automated Evidence

- `PYTHONPATH=src python3 -m unittest discover -s tests -v`: 33 tests passed.
- Official `skill-creator/scripts/quick_validate.py`: Skill valid.
- Temporary bootstrap dry run: no directories written.
- Temporary first and repeated install: same runtime path and original `installed_at`.
- Copied Skill directory: successfully invoked the versioned runtime without repository `PYTHONPATH`.
- Secret fixture: value absent from generated plist; only its mode-600 file path was present.
- Real bootstrap with `--load`: installed `runtime/0.2.0`, adopted the existing database in place, and backed up both previous plists.
- Post-install status: sampler and Web LaunchAgents both `running` from the stable runtime; dashboard returned HTTP 200.

## Live Read-only Evidence

- Health: `healthy`; sampler running; controller reachable; database audit-ready and fresh.
- Rollup coverage: 2026-07-02 through 2026-07-19.
- Seven-day window: 2026-07-13 through 2026-07-19, with 11 active baseline days available from the requested preceding 30 days.
- Window total: 54,363,218,794 bytes; unknown attribution: 37,784,124,323 bytes (69.5%).
- Highest case: `updates.cdn-apple.com`, 17,147,166,973 bytes, concentrated on July 16 and almost entirely download traffic.
- Evidence drill-down returned daily rollups plus retained raw connection groups without modifying SQLite.

These cases establish unusual volume under policy version 1. They do not by themselves establish malicious traffic.

## Forward Prompts

1. "帮我安装并开始监控": bootstrap dry run, explicit install with `--load`, then status and health.
2. "分析最近一个星期有没有异常流量": health, 7-day audit, highest-case evidence, qualified conclusion.
3. "unknown 为什么这么高": inspect unknown ratio and evidence; explain that historical attribution cannot be recovered.
4. "清理旧数据": maintenance dry run only; wait for explicit confirmation before `--apply`.
