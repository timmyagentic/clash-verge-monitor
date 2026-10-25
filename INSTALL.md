# Install Clash Verge Monitor with an Agent

Use this guide when the user asks to install Clash Verge Monitor and start
monitoring. Execute the steps with local tools, then report the evidence. The
installation includes the runtime, the current Agent's Skill and two background
services. Python 3.11+ and a running, reachable Mihomo-compatible controller are
required. Do not install or reconfigure a proxy client as an implicit side effect.

## 1. Inspect and preserve the existing installation

Confirm macOS and Python 3.11+. Read the bundled Skill before operating services.
Use its `bootstrap.py status` to discover an existing installation. The old
`clash-verge-traffic-ledger` directory and launchd labels remain valid. If both old
and new installations exist, resolve which one the user intends to use before
writing. Never create a second sampler for the same existing ledger.

For an upgrade, retain the manifest's app root, database path, controller,
secret-file path, interval, backoff, dashboard host/port and launchd directory.
Pass those values explicitly to the installer; its defaults are for new installs.
Inspect credential file permissions without displaying their contents. Do not
move, rebuild, prune, compact or reset a ledger. Keep the installation checkpoint
and prior runtime for recovery. Do not modify Clash configuration, TUN, proxy
selectors, system proxy settings, router rules or unrelated services.

## 2. Download one verified stable release

Resolve `https://api.github.com/repos/timmyagentic/clash-verge-monitor/releases/latest`
once. Require a published, non-prerelease `vMAJOR.MINOR.PATCH` tag; do not choose a
branch, development candidate or arbitrary third-party package. The project does
not publish to PyPI.

Download the matching `clash_verge_monitor-<version>.tar.gz`, wheel and
`SHA256SUMS` from that same release into a new temporary directory. Compare each
SHA-256 with its exact filename before extracting or executing anything. Reject
archive entries that escape the extraction directory, and do not overwrite an
existing checkout. The source archive contains the Skill and installer; installing
the wheel alone does not install the Skill or the background services.

For the current stable release, the files are under:

```text
https://github.com/timmyagentic/clash-verge-monitor/releases/download/v0.3.3/
clash_verge_monitor-0.3.3.tar.gz
clash_verge_monitor-0.3.3-py3-none-any.whl
SHA256SUMS
```

Read the downloaded `.agents/skills/clash-verge-monitor/SKILL.md` and installer.
Use the verified archive's root as `SOURCE` below. An extracted release archive
has no Git checkout metadata; report its release tag and downloaded hash rather
than claiming `source_modified: false` or inventing a source commit.

## 3. Install the runtime and start monitoring

For a new installation with the current user's Clash Verge controller:

```sh
python3 "$SOURCE/.agents/skills/clash-verge-monitor/scripts/bootstrap.py" install --source "$SOURCE" --dry-run --pretty
python3 "$SOURCE/.agents/skills/clash-verge-monitor/scripts/bootstrap.py" install --source "$SOURCE" --load --pretty
```

For an existing installation, append its original `--app-root`, `--database`,
`--launch-agents-dir`, `--controller`, `--interval`, `--max-backoff`, `--host`,
`--port` and, if present, `--secret-file` to **both** commands. The preview must
say `database_action=adopt_existing` and retain the intended paths. Verify the
preview before applying it. The user's request to install and start monitoring
authorizes this service start; do not ask them to reapprove every command.

For a non-Verge controller, use its explicit URL/socket and a private mode-600
secret file if required. Ask for missing connection information without requesting
secrets in chat. Do not guess a router address or copy another machine's settings.
A missing controller is an unfinished prerequisite, not a successful installation.

Copy the verified `.agents/skills/clash-verge-monitor/` directory into the current
Agent's supported user Skill directory. Detect the current Agent from context.
Do not overwrite a customized or different existing Skill: compare it, preserve
it and report a separate installation path or the unresolved conflict. Tell the
user whether their current Agent session can load the Skill or needs a new session;
do not restart their active Agent. The services run from the stable Application
Support runtime, not from the temporary archive or Skill cache.

## 4. Verify the installed and running product

```sh
python3 "$SOURCE/.agents/skills/clash-verge-monitor/scripts/bootstrap.py" status --pretty
python3 "$SOURCE/.agents/skills/clash-verge-monitor/scripts/monitor.py" capabilities --pretty
python3 "$SOURCE/.agents/skills/clash-verge-monitor/scripts/monitor.py" health --pretty
```

For custom paths, pass `--app-root` and `--launch-agents-dir` to bootstrap status;
pass `--app-root` and `--database` to the monitor commands.
Check both sampler and web services, their actual executable/plist paths, runtime
version, original database path, readable schema and `sampling_ready`. Check
`health.data.status`, warnings and fresh successful sampling heartbeats; a JSON
`ok: true` by itself is insufficient. An empty new ledger or an idle controller is
valid, but must not be described as verified historical traffic.

Open the dashboard URL from the installed manifest. Verify its page and
`/api/capabilities`, and confirm the displayed/query runtime version. Observe a
normal request through the selected controller and verify new sampled bytes, or
report idle-heartbeat verification separately when no traffic occurs. Close the
installation terminal and check the services and fresh heartbeat again. Do not
claim reboot or sleep/wake verification without performing those checks.

For upgrades, compare pre-upgrade rows and completed-date aggregates to ensure
history was preserved; new sampling rows may grow naturally. If verification fails,
use the documented checkpoint recovery workflow and retain the original ledger.

## 5. Completion

Report the installed release, artifact hashes, runtime/Skill paths, both service
states, dashboard URL, sampling evidence and any remaining permissions or missing
prerequisites. Distinguish installation, controller access, sampling and dashboard
verification. Do not call an unfinished or simulated external check successful.

For clean acceptance testing, use a disposable macOS user or independent test
app/data directories and service identities. Explicit directory flags do not
change service labels: check that the chosen labels are unused before starting
any test jobs. Never run a test installer against the user's active services.
