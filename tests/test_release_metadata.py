import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CHECK_RELEASE = ROOT / "scripts" / "check_release.py"


def load_release_module():
    spec = importlib.util.spec_from_file_location("check_release", CHECK_RELEASE)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load release checker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReleaseMetadataTests(unittest.TestCase):
    def test_project_package_and_changelog_versions_match(self):
        release = load_release_module()

        version = release.project_version(ROOT)

        self.assertEqual(release.package_version(ROOT), version)
        self.assertIsNotNone(release.changelog_release_label(version, ROOT))
        self.assertIn("### Added", release.changelog_release_notes(version, ROOT))

    def test_tag_normalization_accepts_conventional_v_prefix(self):
        release = load_release_module()

        self.assertEqual(release.normalized_tag("v0.3.0"), "0.3.0")
        self.assertEqual(release.normalized_tag("0.3.0"), "0.3.0")


if __name__ == "__main__":
    unittest.main()
