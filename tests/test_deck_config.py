/home/eko/.bashrc: line 104: bind: warning: line editing not enabled
import tempfile
import unittest
from pathlib import Path

from deck_config import DeckConfigError, load_decks


class DeckConfigTests(unittest.TestCase):
    def test_loads_deck_and_normalizes_card_body(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "decks.toml"
            source.write_text(
                """
[[decks]]
name = "Writing"

[[decks.cards]]
title = "Shorten"
key = "S"
body = "  Make this shorter.  "
""",
                encoding="utf-8",
            )

            decks = load_decks(source)

            self.assertEqual(decks[0].name, "Writing")
            self.assertEqual(decks[0].cards[0].title, "Shorten")
            self.assertEqual(decks[0].cards[0].key, "S")
            self.assertEqual(decks[0].cards[0].body, "Make this shorter.\n")

    def test_loads_recursive_includes_in_sorted_order_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parts = root / "parts"
            parts.mkdir()
            (root / "decks.toml").write_text(
                'include = ["parts/*.toml"]\n', encoding="utf-8"
            )
            (parts / "20-second.toml").write_text(
                self.deck_text("Second", "B"), encoding="utf-8"
            )
            (parts / "10-first.toml").write_text(
                'include = ["../decks.toml"]\n' + self.deck_text("First", "A"),
                encoding="utf-8",
            )

            decks = load_decks(root / "decks.toml")

            self.assertEqual([deck.name for deck in decks], ["First", "Second"])

    def test_missing_source_has_clear_error(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "missing.toml"

            with self.assertRaisesRegex(DeckConfigError, "Configuration not found"):
                load_decks(source)

    def test_rejects_deck_without_cards(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "decks.toml"
            source.write_text('[[decks]]\nname = "Empty"\n', encoding="utf-8")

            with self.assertRaisesRegex(DeckConfigError, "at least one card"):
                load_decks(source)

    @staticmethod
    def deck_text(name: str, key: str) -> str:
        return f'''\
[[decks]]
name = "{name}"

[[decks.cards]]
title = "Card {name}"
key = "{key}"
body = "Body {name}"
'''


if __name__ == "__main__":
    unittest.main()
