"""Opt-in regression against the real per-user macOS launchd manager.

Only random test labels and temporary files are used; installed services and
ledgers are never selected. Run with CVM_TEST_LAUNCHD=1 on a logged-in Mac.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

from clash_verge_monitor.service import bootstrap_service, service_state
from test_skill_scripts import load_bootstrap_module


@unittest.skipUnless(sys.platform == "darwin" and os.environ.get("CVM_TEST_LAUNCHD") == "1",
                     "requires explicit CVM_TEST_LAUNCHD=1 on macOS")
class RealLaunchdTests(unittest.TestCase):
    def setUp(self):
        self.domain = f"gui/{os.getuid()}"
        subprocess.run(["launchctl", "print", self.domain], check=True,
                       stdout=subprocess.DEVNULL)
        self.label = f"com.example.cvm-test.{uuid.uuid4().hex}"
        self.target = f"{self.domain}/{self.label}"
        self.temporary = tempfile.TemporaryDirectory(prefix="cvm launchd test ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.plist = self.root / "probe.plist"
        self.proof = self.root / "started.json"
        self.plist.write_bytes(plistlib.dumps({
            "Label": self.label,
            "ProgramArguments": [sys.executable, "-I", "-c",
                "import json,os,time; from pathlib import Path; "
                "Path('started.json').write_text(json.dumps({'cwd':os.getcwd(),'pid':os.getpid()})); "
                "time.sleep(60)"],
            "WorkingDirectory": str(self.root),
            "RunAtLoad": True,
            "StandardErrorPath": str(self.root / "stderr.log"),
        }))
        self.addCleanup(self.remove_test_job)

    def remove_test_job(self):
        subprocess.run(["launchctl", "bootout", self.target], capture_output=True)
        # Do not leave the test label disabled after the regression.
        subprocess.run(["launchctl", "enable", self.target], check=True)
        result = subprocess.run(["launchctl", "print", self.target], capture_output=True)
        self.assertNotEqual(result.returncode, 0, "test job was not removed")

    def wait_for_process(self, previous_pid=None):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.proof.exists():
                try:
                    proof = json.loads(self.proof.read_text())
                except json.JSONDecodeError:
                    continue
                state = subprocess.run(["launchctl", "print", self.target],
                                       capture_output=True, text=True)
                pid = re.search(r"(?m)^\s+pid = (\d+)$", state.stdout)
                if (proof["pid"] != previous_pid and pid
                        and int(pid.group(1)) == proof["pid"]
                        and service_state(self.label) == "running"):
                    self.assertEqual(Path(proof["cwd"]).resolve(), self.root.resolve())
                    return proof["pid"]
            time.sleep(0.05)
        self.fail("real launchd did not start the test process in its working directory")

    def test_cli_recovers_previously_disabled_job(self):
        subprocess.run(["launchctl", "disable", self.target], check=True)
        # Demonstrate the failure produced by the old bootstrap-before-enable order.
        failed = subprocess.run(["launchctl", "bootstrap", self.domain, str(self.plist)],
                                capture_output=True)
        self.assertNotEqual(failed.returncode, 0, "disabled-job precondition not reproduced")
        bootstrap_service(self.label, self.plist)
        self.wait_for_process()

    def test_skill_reload_recovers_after_unload(self):
        bootstrap = load_bootstrap_module()
        bootstrap.load_service(self.label, self.plist)
        first_pid = self.wait_for_process()
        bootstrap.unload_service(self.label, self.plist)
        self.assertNotEqual(service_state(self.label), "running")
        bootstrap.load_service(self.label, self.plist)
        self.wait_for_process(previous_pid=first_pid)
