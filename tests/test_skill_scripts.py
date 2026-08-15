import importlib.util
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from clash_verge_traffic_ledger.models import TrafficDelta
from clash_verge_traffic_ledger.store import LedgerStore


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents" / "skills" / "clash-verge-traffic-auditor"
BOOTSTRAP = SKILL / "scripts" / "bootstrap.py"
AUDITOR = SKILL / "scripts" / "traffic_auditor.py"


def run_json(script, *arguments, cwd=ROOT):
    completed = subprocess.run(
        [sys.executable, str(script), *map(str, arguments)],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        document = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"script returned invalid JSON\nstdout={completed.stdout}\nstderr={completed.stderr}"
        ) from exc
    return completed, document


def seed_database(path):
    store = LedgerStore(path)
    store.record_deltas(
        [
            TrafficDelta(
                ts=datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc),
                date="2026-07-19",
                connection_id="test",
                process="TestApp",
                host="test.example",
                destination_ip="1.2.3.4",
                source_ip="127.0.0.1",
                source_port=50000,
                destination_port=443,
                network="tcp",
                connection_type="HTTP",
                chains=["Proxy"],
                rule="MATCH",
                upload_bytes=10,
                download_bytes=20,
            )
        ]
    )


def load_bootstrap_module():
    script_dir = str(BOOTSTRAP.parent)
    sys.path.insert(0, script_dir)
    try:
        spec = importlib.util.spec_from_file_location(
            "traffic_auditor_bootstrap",
            BOOTSTRAP,
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("could not load bootstrap module")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(script_dir)


class BootstrapScriptTests(unittest.TestCase):
    def test_source_modified_includes_untracked_files(self):
        bootstrap = load_bootstrap_module()
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=source, check=True)

            self.assertFalse(bootstrap.source_modified(source))
            (source / "untracked.py").write_text("value = 1\n", encoding="utf-8")
            self.assertTrue(bootstrap.source_modified(source))

    def test_launchctl_parser_uses_top_level_job_state(self):
        bootstrap = load_bootstrap_module()
        details = bootstrap.parse_launchctl_output(
            """
            path = /tmp/example.plist
            state = running
            coalition = {
                state = active
            }
            """
        )

        self.assertEqual(details["state"], "running")
        self.assertEqual(details["plist"], "/tmp/example.plist")

    def test_install_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app_root = root / "Application Support" / "ledger"
            launch_agents = root / "LaunchAgents"

            completed, document = run_json(
                BOOTSTRAP,
                "install",
                "--source",
                ROOT,
                "--app-root",
                app_root,
                "--launch-agents-dir",
                launch_agents,
                "--dry-run",
            )

            self.assertEqual(completed.returncode, 0)
            self.assertTrue(document["data"]["dry_run"])
            self.assertFalse(app_root.exists())
            self.assertFalse(launch_agents.exists())

    def test_install_is_idempotent_and_copied_skill_uses_stable_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app_root = root / "Application Support" / "ledger"
            launch_agents = root / "LaunchAgents"
            database = root / "existing" / "ledger.sqlite"
            secret_file = root / "controller.secret"
            database.parent.mkdir(parents=True)
            seed_database(database)
            secret_file.write_text("super-secret\n", encoding="utf-8")
            secret_file.chmod(0o600)
            arguments = [
                "install",
                "--source",
                ROOT,
                "--app-root",
                app_root,
                "--launch-agents-dir",
                launch_agents,
                "--database",
                database,
                "--secret-file",
                secret_file,
                "--bootstrap-python",
                sys.executable,
            ]

            first, first_document = run_json(BOOTSTRAP, *arguments)
            second, second_document = run_json(BOOTSTRAP, *arguments)

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            first_manifest = first_document["data"]["manifest"]
            second_manifest = second_document["data"]["manifest"]
            self.assertEqual(first_manifest["installed_at"], second_manifest["installed_at"])
            self.assertEqual(first_manifest["runtime_python"], second_manifest["runtime_python"])
            runtime_python = Path(second_manifest["runtime_python"])
            self.assertTrue(runtime_python.is_file())
            self.assertEqual(Path(second_manifest["database"]), database.resolve())

            sampler_plist = launch_agents / "com.timmy.clash-verge-traffic-ledger.plist"
            plist_bytes = sampler_plist.read_bytes()
            plist = plistlib.loads(plist_bytes)
            self.assertEqual(plist["ProgramArguments"][0], str(runtime_python))
            self.assertNotIn(str(ROOT / ".venv"), plist_bytes.decode("utf-8"))
            self.assertNotIn("super-secret", plist_bytes.decode("utf-8"))
            self.assertIn(str(secret_file.resolve()), plist["ProgramArguments"])

            copied_skill = root / "copied-skill"
            shutil.copytree(SKILL, copied_skill)
            completed, audit = run_json(
                copied_skill / "scripts" / "traffic_auditor.py",
                "audit",
                "--app-root",
                app_root,
                "--end-date",
                "2026-07-19",
                cwd=root,
            )
            self.assertEqual(completed.returncode, 0, json.dumps(audit, indent=2))
            self.assertEqual(audit["operation"], "audit")
            self.assertEqual(audit["data"]["summary"]["total_bytes"], 30)

            clean_environment = os.environ.copy()
            clean_environment.pop("PYTHONPATH", None)
            clean_environment.pop("PYTHONHOME", None)
            imported = subprocess.run(
                [
                    str(runtime_python),
                    "-c",
                    "import clash_verge_traffic_ledger as p; print(p.__file__)",
                ],
                cwd=root,
                capture_output=True,
                text=True,
                env=clean_environment,
                check=True,
            )
            self.assertIn(str(app_root / "runtime"), imported.stdout)

            uninstall, uninstall_document = run_json(
                BOOTSTRAP,
                "uninstall",
                "--app-root",
                app_root,
                "--launch-agents-dir",
                launch_agents,
            )
            self.assertEqual(uninstall.returncode, 0)
            self.assertTrue(uninstall_document["data"]["dry_run"])
            self.assertTrue(runtime_python.is_file())
            self.assertTrue(database.is_file())


if __name__ == "__main__":
    unittest.main()
