import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QFocusEvent, QKeyEvent, QPalette
from PySide6.QtWidgets import QApplication
from unittest.mock import patch

from promptdeck.app import PromptDeck, ThemeColors
from promptdeck.config import AppConfig, Appearance, Card, Deck
from promptdeck.setup_ui import SetupDialog


class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def deck_widget(self):
        path = Path("/example/decks.toml")
        decks = [
            Deck("AI", [Card("Tone", "Tone\n", "T"), Card("Email", "Email\n", "E")]),
            Deck("Solid State", [Card("Teaching", "Teaching\n", "T")]),
            Deck("Microscopy", [Card("Images", "Images\n", "I")]),
            Deck("Solid Advice", [Card("Review", "Review\n", "R")]),
        ]
        return PromptDeck(AppConfig(path, path, Appearance(), decks))

    def press(self, widget, key, text="", modifiers=Qt.NoModifier):
        event = QKeyEvent(QEvent.KeyPress, key, modifiers, text)
        widget.keyPressEvent(event)

    def type_text(self, widget, text):
        for character in text:
            key = Qt.Key_Space if character == " " else ord(character.upper())
            self.press(widget, key, character)

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

    def test_deck_finder_previews_and_commits_first_alphabetical_prefix(self):
        widget = self.deck_widget()
        self.press(widget, Qt.Key_E, "e")
        self.assertEqual(widget.card_index, 1)

        self.press(widget, Qt.Key_Slash, "/")
        self.type_text(widget, "solid")
        self.assertTrue(widget.deck_finder_open)
        self.assertEqual(widget.deck_query, "solid")
        self.assertEqual(widget.deck.name, "Solid Advice")
        self.assertEqual(widget.card_index, 0)

        self.press(widget, Qt.Key_Return)
        self.assertFalse(widget.deck_finder_open)
        self.assertEqual(widget.deck.name, "Solid Advice")
        self.assertEqual(widget.card_index, 0)

    def test_deck_finder_escape_restores_original_deck_and_card(self):
        widget = self.deck_widget()
        widget.card_index = 1
        self.press(widget, Qt.Key_Slash, "/")
        self.type_text(widget, "micro")
        self.assertEqual(widget.deck.name, "Microscopy")
        self.press(widget, Qt.Key_Escape)
        self.assertFalse(widget.deck_finder_open)
        self.assertEqual(widget.deck.name, "AI")
        self.assertEqual(widget.card_index, 1)

    def test_deck_finder_empty_and_no_match_restore_original_cards(self):
        widget = self.deck_widget()
        widget.card_index = 1
        self.press(widget, Qt.Key_Slash, "/")
        self.type_text(widget, "micro")
        self.assertEqual(widget.deck.name, "Microscopy")
        for _ in "micro":
            self.press(widget, Qt.Key_Backspace)
        self.assertTrue(widget.deck_finder_open)
        self.assertEqual(widget.deck.name, "AI")
        self.assertEqual(widget.card_index, 1)

        self.type_text(widget, "state")
        self.assertIsNone(widget.matching_deck_index)
        self.assertEqual(widget.deck.name, "AI")
        self.assertEqual(widget.card_index, 1)
        self.press(widget, Qt.Key_Return)
        self.assertTrue(widget.deck_finder_open)
        for _ in "state":
            self.press(widget, Qt.Key_Backspace)
        self.press(widget, Qt.Key_Backspace)
        self.assertFalse(widget.deck_finder_open)
        self.assertEqual(widget.deck.name, "AI")
        self.assertEqual(widget.card_index, 1)

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
