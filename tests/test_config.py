import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from promptdeck.config import DeckConfigError, config_path, load_app_config, load_decks


DECK = '''[[decks]]
name = "Writing"
[[decks.cards]]
title = "Shorten"
key = "S"
body = "  Make this shorter.  "
'''


class ConfigTests(unittest.TestCase):
    def test_loads_app_config_and_relative_decks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.toml").write_text(
                'version = 1\ndeck_source = "decks.toml"\n'
                '[appearance]\ntheme = "system"\naccent = "#336699"\n'
                'card_background = "#18181b"\n',
                encoding="utf-8",
            )
            (root / "decks.toml").write_text(DECK, encoding="utf-8")
            config = load_app_config(root / "config.toml")
            self.assertEqual(config.appearance.selected_background, "#336699")
            self.assertEqual(config.appearance.card_background, "#18181b")
            self.assertEqual(config.decks[0].cards[0].body, "Make this shorter.\n")

    def test_explicit_config_precedes_environment(self):
        with patch.dict(os.environ, {"PROMPTDECK_CONFIG": "/environment.toml"}):
            self.assertEqual(config_path(Path("explicit.toml")), Path("explicit.toml").resolve())

    def test_loads_recursive_includes_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "decks.toml").write_text('include = ["parts/*.toml"]\n', encoding="utf-8")
            (root / "parts").mkdir()
            (root / "parts" / "a.toml").write_text('include = ["../decks.toml"]\n' + DECK, encoding="utf-8")
            self.assertEqual(len(load_decks(root / "decks.toml")), 1)

    def test_globbed_decks_keep_filename_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parts = root / "parts"
            parts.mkdir()
            (root / "decks.toml").write_text(
                'include = ["parts/*.toml"]\n', encoding="utf-8"
            )

            def deck(name):
                return (
                    f'[[decks]]\nname = "{name}"\n[[decks.cards]]\n'
                    'title = "Test"\nbody = "Test"\n'
                )

            files = {
                "20-microscopy.toml": "Microscopy",
                "00-ai.toml": "AI",
                "10-solid-state.toml": "Solid State",
                "personal.toml": "Personal",
            }
            for filename, name in files.items():
                (parts / filename).write_text(deck(name), encoding="utf-8")

            names = [deck.name for deck in load_decks(root / "decks.toml")]
            self.assertEqual(names, ["AI", "Solid State", "Microscopy", "Personal"])

    def test_rejects_invalid_accent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.toml").write_text('[appearance]\naccent = "blue"\n', encoding="utf-8")
            with self.assertRaisesRegex(DeckConfigError, "selected_background"):
                load_app_config(root / "config.toml")

    def test_rejects_invalid_card_color(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.toml").write_text(
                '[appearance]\ncard_border = "gray"\n', encoding="utf-8"
            )
            with self.assertRaisesRegex(DeckConfigError, "card_border"):
                load_app_config(root / "config.toml")


if __name__ == "__main__":
    unittest.main()
