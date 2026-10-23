# Clash Verge Monitor rename

The product is now **Clash Verge Monitor**, formerly Clash Verge Traffic Ledger.
The renamed source prepares **0.3.2**; it is not a published release yet.

| Surface | Current identity |
| --- | --- |
| Repository / distribution / command | `clash-verge-monitor` |
| Python module | `clash_verge_monitor` |
| Agent Skill | `.agents/skills/clash-verge-monitor/` |
| Agent wrapper | `scripts/monitor.py` inside the Skill |
| New installation root | `~/Library/Application Support/clash-verge-monitor/` |
| New sampler / web services | `com.timmy.clash-verge-monitor` / `.web` |
| Prepared website domain | `https://clash-verge-monitor.timmyagentic.si` |

## Existing installations

- The old `clash-verge-traffic-ledger` console command and
  `python -m clash_verge_traffic_ledger` remain compatibility entry points.
- Bootstrap detects the existing `~/Library/Application Support/clash-verge-traffic-ledger/`
  directory and reuses it. It does not move a database, virtual environment or logs.
  If both roots exist, explicitly select `--app-root` after inspecting them.
- Upgrades reuse the database recorded in `install.json` unless `--database` is
  explicitly supplied. No retention, compaction or data rewrite is part of renaming.
- Existing `com.timmy.clash-verge-traffic-ledger` launchd labels are retained during
  upgrade and rollback. Creating a second collector under another label could count
  traffic twice. New installations use Monitor labels. Duplicate identities block
  installation until resolved.
- The new Skill can query an old installed runtime using its original module name.
  Updated runtimes also carry the old module alias for already-copied Skills.
- The Skill folder itself is renamed. Update manually configured Skill paths and
  invocation names to `clash-verge-monitor`; old copied Skills are not deleted.

## Published downloads and historical evidence

The v0.3.1 release is immutable. Its wheel is still named
`clash_verge_traffic_ledger-0.3.1-py3-none-any.whl`, and that wheel uses the old module.
Website stable-install commands deliberately match that release. New build artifacts
use `clash_verge_monitor`. Publishing 0.3.2 is a separate release action.

Dated design plans, verification runs and screenshots retain the name visible when
captured. They are historical evidence, not screenshots of the renamed build.
The local control-plane project ID and canonical checkout path are also historical
identifiers; source checkout directories and other worktrees are not moved by this change.

## Website rollout

The current Cloudflare Worker resource `traffic-ledger-site` is retained so that
existing domain ownership and deployment history stay attached to the same service.
The prepared config adds the new domain and keeps the old domain for redirects.
Deploy both domains together, verify HTTPS and path-preserving redirects, then update
external website links. Source changes do not prove the production site was deployed.
