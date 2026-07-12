import tempfile
import unittest
from pathlib import Path, PurePosixPath
from unittest.mock import patch

from promptdeck.cli import copy_tree_without_overwrite, parser, service_unit


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


if __name__ == "__main__":
    unittest.main()
