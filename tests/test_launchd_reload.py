"""A disabled launchd job must be enabled before it can be bootstrapped."""
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from clash_verge_monitor.service import bootstrap_service
from test_skill_scripts import load_bootstrap_module


class DisabledLaunchd:
    def __init__(self):
        self.disabled = True
        self.loaded = False

    def __call__(self, arguments, *, check=False, **kwargs):
        command = arguments[1]
        code = 0
        if command == "enable":
            self.disabled = False
        elif command == "disable":
            self.disabled = True
        elif command == "bootout":
            self.loaded = False
        elif command == "bootstrap":
            if self.disabled:
                code = 5
            else:
                self.loaded = True
        elif command == "kickstart" and not self.loaded:
            code = 3
        if code and check:
            raise subprocess.CalledProcessError(code, arguments)
        return subprocess.CompletedProcess(arguments, code)


class LaunchdReloadTests(unittest.TestCase):
    def test_cli_can_install_previously_disabled_job(self):
        launchd = DisabledLaunchd()
        bootstrap_service("com.example.monitor", "/tmp/example.plist", runner=launchd)
        self.assertTrue(launchd.loaded)
        self.assertFalse(launchd.disabled)

    def test_skill_reload_restores_job_after_unload_disables_it(self):
        bootstrap = load_bootstrap_module()
        launchd = DisabledLaunchd()
        with patch.object(bootstrap.subprocess, "run", side_effect=launchd):
            bootstrap.unload_service("com.example.monitor", Path("/tmp/example.plist"))
            bootstrap.load_service("com.example.monitor", Path("/tmp/example.plist"))
        self.assertTrue(launchd.loaded)
        self.assertFalse(launchd.disabled)
