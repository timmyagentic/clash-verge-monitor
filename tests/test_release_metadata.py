import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile


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


class DistributionContentTests(unittest.TestCase):
    def check_artifacts(self, *, asset=b"body{}", metadata=b"Version: 0.3.1\n"):
        release = load_release_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src/clash_verge_monitor/assets/site.css"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"body{}")
            prefix = "clash_verge_monitor-0.3.1"
            with tarfile.open(root / f"{prefix}.tar.gz", "w:gz") as archive:
                names = [".agents/skills/clash-verge-monitor/SKILL.md",
                         "CHANGELOG.md", "docs/releasing.md", "scripts/check_release.py",
                         "src/clash_verge_monitor/__init__.py",
                         "src/clash_verge_monitor/assets/site.css"]
                for name in names:
                    content = b"body{}" if name.endswith(".css") else b"fixture\n"
                    member = tarfile.TarInfo(f"{prefix}/{name}")
                    member.size = len(content)
                    archive.addfile(member, io.BytesIO(content))
            with zipfile.ZipFile(root / f"{prefix}-py3-none-any.whl", "w") as archive:
                archive.writestr("clash_verge_monitor/__init__.py", b"fixture\n")
                archive.writestr(f"{prefix}.dist-info/entry_points.txt", b"fixture\n")
                if metadata is not None:
                    archive.writestr(f"{prefix}.dist-info/METADATA", metadata)
                archive.writestr("clash_verge_monitor/assets/site.css", asset)
            with patch.object(release, "ROOT", root):
                return release.distribution_errors(root, "0.3.1")

    def test_matching_dashboard_assets_and_version_are_accepted(self):
        self.assertEqual(self.check_artifacts(), [])

    def test_changed_dashboard_asset_and_wrong_version_block_release(self):
        self.assertTrue(any("asset" in error for error in self.check_artifacts(asset=b"changed")))
        self.assertTrue(any("version" in error for error in self.check_artifacts(metadata=b"Version: 0.3.0\n")))

    def test_missing_metadata_returns_a_validation_error(self):
        self.assertTrue(any("METADATA" in error for error in self.check_artifacts(metadata=None)))


if __name__ == "__main__":
    unittest.main()
