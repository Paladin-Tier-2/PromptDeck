import tempfile
import unittest
from pathlib import Path, PurePosixPath
from unittest.mock import patch

from promptdeck.cli import (
    copy_tree_without_overwrite,
    finish_setup,
    parser,
    service_unit,
)
from promptdeck.config import config_dir


class CliTests(unittest.TestCase):
    def test_parses_service_and_setup_commands(self):
        self.assertEqual(parser().parse_args(["service", "stop"]).action, "stop")
        self.assertTrue(parser().parse_args(["setup", "--yes"]).yes)
        self.assertFalse(parser().parse_args(["setup"]).terminal)
        self.assertTrue(parser().parse_args(["setup", "--terminal"]).terminal)

    def test_migration_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            (source / "deck.toml").write_text("new", encoding="utf-8")
            (target / "deck.toml").write_text("private", encoding="utf-8")
            copy_tree_without_overwrite(source, target)
            self.assertEqual((target / "deck.toml").read_text(encoding="utf-8"), "private")

    def test_service_runs_installed_command_without_hardcoded_environment(self):
        unit = service_unit(PurePosixPath("/opt/promptdeck/bin/promptdeck"))
        self.assertIn("ExecStart=/opt/promptdeck/bin/promptdeck daemon", unit)
        self.assertIn("Restart=on-failure", unit)
        self.assertNotIn("Environment=", unit)

    def test_repeated_setup_preserves_an_explicit_accent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = {
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "APPDATA": str(root / "config"),
            }
            with (
                patch.dict("os.environ", environment),
                patch("promptdeck.cli.print_shortcut_help"),
                patch("builtins.print"),
            ):
                self.assertEqual(finish_setup(None, "#7c3aed", True, False), 0)
                self.assertEqual(finish_setup(None, "system", False, False), 0)
                settings = config_dir() / "config.toml"
            self.assertIn('accent = "#7c3aed"', settings.read_text())

    def test_unchecked_autostart_removes_an_existing_service(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = {
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "APPDATA": str(root / "config"),
            }
            unit = root / "config" / "systemd" / "user" / "promptdeck.service"
            unit.parent.mkdir(parents=True)
            unit.touch()
            with (
                patch.dict("os.environ", environment),
                patch("promptdeck.cli.service") as service,
                patch("promptdeck.cli.print_shortcut_help"),
                patch("builtins.print"),
            ):
                finish_setup(None, "system", True, False)
            service.assert_called_once_with("uninstall")


if __name__ == "__main__":
    unittest.main()
