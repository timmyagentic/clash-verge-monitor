import importlib.util
from pathlib import Path
import sys
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
try:
    spec = importlib.util.spec_from_file_location("repository_policy", SCRIPTS / "check_repository_policy.py")
    policy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(policy)
finally:
    sys.path.remove(str(SCRIPTS))


class RepositoryPolicyTests(unittest.TestCase):
    def test_next_patch_and_its_published_tag_are_accepted(self):
        for tags in (["v0.3.0"], ["v0.3.0", "v0.3.1"], ["v0.3.0", "v0.4.0rc1"]):
            self.assertEqual(policy.patch_version_errors("0.3.1", tags), [])

    def test_jumps_prereleases_and_regressions_are_rejected(self):
        for version in ("0.3.3", "0.4.0", "1.0.0", "0.3.1rc1", "0.3.01"):
            self.assertTrue(policy.patch_version_errors(version, ["v0.3.0"]))
        self.assertTrue(policy.patch_version_errors("0.3.0", ["v0.3.0", "v0.3.1"]))

    def test_a_missing_tag_baseline_is_not_silently_accepted(self):
        self.assertTrue(policy.patch_version_errors("0.3.1", []))


if __name__ == "__main__":
    unittest.main()
