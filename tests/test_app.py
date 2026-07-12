/home/eko/.bashrc: line 104: bind: warning: line editing not enabled
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from promptdeck.app import PromptDeck, ThemeColors
from promptdeck.config import AppConfig, Appearance, Card, Deck


class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_custom_accent_uses_readable_selected_text(self):
        palette = QPalette()
        dark = ThemeColors.from_palette(palette, "#112233")
        light = ThemeColors.from_palette(palette, "#f0eedd")
        self.assertEqual(dark.selected_text, QColor("#ffffff"))
        self.assertEqual(light.selected_text, QColor("#000000"))

    def test_qt_clipboard_is_primary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decks.toml"
            config = AppConfig(path, path, Appearance(), [Deck("Test", [Card("Copy", "clipboard text\n")])])
            widget = PromptDeck(config, daemon=True)
            widget.copy_selected()
            self.assertEqual(self.app.clipboard().text(), "clipboard text\n")


if __name__ == "__main__":
    unittest.main()
