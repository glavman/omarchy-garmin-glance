"""Installer packaging tests using only temporary files and mocked commands."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch


SPEC = importlib.util.spec_from_file_location("install", Path(__file__).resolve().parents[1] / "install.py")
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)

ROOT_FILES = (
    "manifest.json", "Service.qml", "BarWidget.qml", "Panel.qml",
    "Chart.qml", "MetricCard.qml", "WatchFace.qml", "WatchIcon.qml", "ActivityIcon.qml", "StressChart.qml", "Model.js", "Grafana.js", "backend.py",
    "README.md", "LICENSE", "install.py",
)
PLUGIN_ID = "io.github.glavman.garmin-glance"


class InstallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.staging = self.root / "staging"
        for name in ROOT_FILES:
            (self.source / name).write_text(name)
        (self.source / "manifest.json").write_text(json.dumps({"id": PLUGIN_ID}))

    def test_only_allowlisted_files_are_copied(self):
        extras = (
            ".env", "connection.json", "tokens.json", "secrets/password",
            "garminconnect-tokens/oauth.json", "exports/health.csv",
            "screenshots/dashboard.png", ".git/config", "__pycache__/backend.pyc",
            "tests/test_backend.py", "unknown.qml", "docs/private.md",
            "docs/nested/SETUP.md",
        )
        docs = ("docs/SETUP.md", "docs/PUBLISHING.md", "docs/REFERENCE.md")
        for name in extras + docs:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name)
        (self.source / "unknown-link").symlink_to(self.root, target_is_directory=True)

        installer.copy_package(self.source, self.staging)

        expected = set(ROOT_FILES + docs)
        self.assertEqual(
            {str(path.relative_to(self.staging)) for path in self.staging.rglob("*") if path.is_file()},
            expected,
        )
        self.assertEqual(
            {str(path.relative_to(self.staging)) for path in self.staging.rglob("*") if path.is_dir()},
            {"docs"},
        )
        for name in expected:
            self.assertEqual((self.staging / name).read_bytes(), (self.source / name).read_bytes())

    def test_optional_docs_can_be_absent(self):
        installer.copy_package(self.source, self.staging)
        self.assertEqual({path.name for path in self.staging.iterdir()}, set(ROOT_FILES))

    def test_symlinked_allowed_files_are_rejected(self):
        secret = self.root / "secret"
        secret.write_text("not package content")
        for name in ROOT_FILES + ("docs/SETUP.md", "docs/PUBLISHING.md", "docs/REFERENCE.md"):
            for target in (secret, self.root / "missing"):
                with self.subTest(name=name, target=target.name):
                    path = self.source / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.unlink(missing_ok=True)
                    path.symlink_to(target)
                    with self.assertRaisesRegex(ValueError, "symlink"):
                        installer.copy_package(self.source, self.staging)
                    self.assertFalse(self.staging.exists())
                    path.unlink()
                    if name in ROOT_FILES:
                        path.write_text(name)

    def test_symlinked_docs_directory_is_rejected(self):
        for target in (self.root, self.root / "missing"):
            with self.subTest(target=target.name):
                docs = self.source / "docs"
                docs.symlink_to(target, target_is_directory=True)
                with self.assertRaisesRegex(ValueError, "symlink"):
                    installer.copy_package(self.source, self.staging)
                self.assertFalse(self.staging.exists())
                docs.unlink()

    def test_symlinked_source_directory_is_rejected(self):
        linked = self.root / "linked"
        linked.symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            installer.copy_package(linked, self.staging)

    def test_missing_or_directory_runtime_file_is_rejected(self):
        path = self.source / "Service.qml"
        path.unlink()
        with self.assertRaisesRegex(ValueError, "Service.qml"):
            installer.copy_package(self.source, self.staging)
        path.mkdir()
        with self.assertRaisesRegex(ValueError, "Service.qml"):
            installer.copy_package(self.source, self.staging)
        self.assertFalse(self.staging.exists())

    def test_install_from_destination_refuses_before_commands_or_rename(self):
        destination = self.root / ".config/omarchy/plugins" / PLUGIN_ID
        destination.parent.mkdir(parents=True)
        self.source.rename(destination)
        with patch.object(installer, "__file__", str(destination / "install.py")), \
                patch.object(installer.Path, "home", return_value=self.root), \
                patch.object(installer.subprocess, "run") as run, \
                patch.object(installer.os, "rename") as rename:
            with self.assertRaisesRegex(SystemExit, "source directory"):
                installer.main()
        run.assert_not_called()
        rename.assert_not_called()
        self.assertTrue((destination / "manifest.json").is_file())

    def test_update_validates_package_roots_and_preserves_backup(self):
        config = self.root / ".config/omarchy"
        destination = config / "plugins" / PLUGIN_ID
        destination.mkdir(parents=True)
        (destination / "manifest.json").write_text(json.dumps({"id": PLUGIN_ID}))
        (destination / "old.txt").write_text("existing install")
        (config / "shell.json").write_text("{}")
        validated = []

        def run(command, **kwargs):
            if command[:3] == ["omarchy", "plugin", "validate"]:
                package = Path(command[3])
                self.assertEqual(json.loads((package / "manifest.json").read_text())["id"], PLUGIN_ID)
                validated.append(package)
            return Mock(stdout=json.dumps([{"id": PLUGIN_ID}]))

        with patch.object(installer, "__file__", str(self.source / "install.py")), \
                patch.object(installer.Path, "home", return_value=self.root), \
                patch.object(installer.subprocess, "run", side_effect=run), \
                patch("builtins.print"):
            installer.main()

        self.assertEqual(len(validated), 2)
        self.assertEqual(validated[0], self.source)
        self.assertEqual(validated[1].name, PLUGIN_ID)
        self.assertEqual({path.name for path in destination.iterdir()}, set(ROOT_FILES))
        backups = list((config / "plugin-backups").iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "old.txt").read_text(), "existing install")
        self.assertEqual((backups[0] / "manifest.json").read_bytes(), (destination / "manifest.json").read_bytes())
        shell_backups = list(config.glob("shell.json.before-garmin-*"))
        self.assertEqual(len(shell_backups), 1)
        self.assertEqual(shell_backups[0].read_text(), "{}")


if __name__ == "__main__":
    unittest.main()
