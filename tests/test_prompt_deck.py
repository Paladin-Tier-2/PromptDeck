/home/eko/.bashrc: line 104: bind: warning: line editing not enabled
import sys
import unittest
from pathlib import Path

import prompt_deck


class CommandLineTests(unittest.TestCase):
    def test_accepts_explicit_config_path(self):
        args, qt_args = prompt_deck.parse_args(
            ["--config", "custom.toml", "--daemon", "--style", "Fusion"]
        )

        self.assertEqual(args.config, Path("custom.toml"))
        self.assertTrue(args.daemon)
        self.assertEqual(qt_args, ["--style", "Fusion"])

    def test_explicit_config_path_takes_priority(self):
        source = prompt_deck.deck_source(Path("custom.toml"))

        self.assertEqual(source, Path("custom.toml").resolve())


@unittest.skipUnless(sys.platform == "win32", "Windows clipboard behavior")
class WindowsClipboardTests(unittest.TestCase):
    def test_copies_with_qt_clipboard(self):
        app = prompt_deck.QApplication.instance() or prompt_deck.QApplication([])
        decks = [
            prompt_deck.Deck(
                name="Test",
                cards=[prompt_deck.Card(title="Copy", body="clipboard text\n")],
            )
        ]
        widget = prompt_deck.PromptDeck(decks, source=Path("unused.toml"))

        widget.copy_selected()

        self.assertEqual(app.clipboard().text(), "clipboard text\n")


if __name__ == "__main__":
    unittest.main()
