import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtGui import QColor, QFocusEvent, QPalette
from PySide6.QtWidgets import QApplication
from unittest.mock import patch

from promptdeck.app import PromptDeck, ThemeColors
from promptdeck.config import AppConfig, Appearance, Card, Deck
from promptdeck.setup_ui import SetupDialog


class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_custom_accent_uses_readable_selected_text(self):
        palette = QPalette()
        dark = ThemeColors.from_palette(
            palette, Appearance(selected_background="#112233")
        )
        light = ThemeColors.from_palette(
            palette, Appearance(selected_background="#f0eedd")
        )
        self.assertEqual(dark.selected_text, QColor("#ffffff"))
        self.assertEqual(light.selected_text, QColor("#000000"))
        palette.setColor(QPalette.Accent, QColor("#f0eedd"))
        system = ThemeColors.from_palette(palette, Appearance())
        self.assertEqual(system.selected_text, QColor("#000000"))

    def test_qt_clipboard_is_primary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decks.toml"
            config = AppConfig(path, path, Appearance(), [Deck("Test", [Card("Copy", "clipboard text\n")])])
            widget = PromptDeck(config, daemon=True)
            widget.copy_selected()
            self.assertEqual(self.app.clipboard().text(), "clipboard text\n")

    def test_denied_startup_focus_does_not_close_overlay(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decks.toml"
            config = AppConfig(path, path, Appearance(), [Deck("Test", [Card("Card", "Body\n")])])
            widget = PromptDeck(config)
            event = QFocusEvent(QEvent.FocusOut)
            with patch.object(widget, "close") as close:
                widget.focusOutEvent(event)
                close.assert_not_called()
                widget.has_been_active = True
                widget.focusOutEvent(event)
                close.assert_called_once()

    def test_setup_dialog_returns_visible_choices(self):
        source = Path("/example/decks.toml")
        dialog = SetupDialog(source, Appearance(), True)
        choices = dialog.choices()
        self.assertEqual(choices.source, source)
        self.assertEqual(choices.appearance.selected_background, "system")
        self.assertTrue(choices.install_service)

        dialog.preview_color("selected_background", QColor("#d946ef"))
        dialog.preview_color("card_background", QColor("#18181b"))
        self.assertEqual(dialog.preview.theme.accent, QColor("#d946ef"))
        self.assertEqual(dialog.preview.theme.card, QColor("#18181b"))
        self.assertIn('selected_background = "#d946ef"', dialog.toml.toPlainText())
        self.assertIn('card_background = "#18181b"', dialog.toml.toPlainText())
        self.assertTrue(dialog.preview.selection_visible)

        dialog.show_page(1)
        self.assertFalse(dialog.back_button.isHidden())
        self.assertTrue(dialog.next_button.isHidden())
        self.assertFalse(dialog.reset_buttons["selected_background"].isHidden())
        self.assertTrue(dialog.reset_buttons["card_border"].isHidden())


if __name__ == "__main__":
    unittest.main()
