"""Qt overlay, palette handling, clipboard access, and daemon socket."""

import math
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, QRectF, QSocketNotifier, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPalette,
    QPen,
)
from PySide6.QtWidgets import QApplication, QWidget

from .config import AppConfig, Card, Deck, load_app_config

IS_WINDOWS = sys.platform == "win32"


def socket_path() -> Path:
    """Return the per-user daemon socket path."""
    if IS_WINDOWS:
        return Path(tempfile.gettempdir()) / "promptdeck.sock"
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    return runtime / "promptdeck.sock"


@dataclass(frozen=True)
class ThemeColors:
    """Colors derived from the active Qt palette and accent setting."""

    window: QColor
    text: QColor
    body_text: QColor
    card: QColor
    muted: QColor
    accent: QColor
    selected_text: QColor
    error: QColor

    @classmethod
    def from_palette(
        cls, palette: QPalette, accent: str = "system"
    ) -> "ThemeColors":
        """Build overlay colors from a Qt palette and optional hex accent."""
        accent_color = palette.color(QPalette.Accent)
        selected_text = palette.color(QPalette.HighlightedText)
        if accent != "system":
            accent_color = QColor(accent)
            luminance = (
                0.2126 * accent_color.red()
                + 0.7152 * accent_color.green()
                + 0.0722 * accent_color.blue()
            ) / 255
            selected_text = QColor("#000000" if luminance > 0.55 else "#ffffff")
        return cls(
            palette.color(QPalette.Window),
            palette.color(QPalette.WindowText),
            palette.color(QPalette.Text),
            palette.color(QPalette.Button),
            palette.color(QPalette.Mid),
            accent_color,
            selected_text,
            palette.color(QPalette.BrightText),
        )

    def alpha(self, color: QColor, opacity: int) -> QColor:
        """Return a copy of *color* with the requested opacity."""
        result = QColor(color)
        result.setAlpha(opacity)
        return result

    def lighter(self, factor: int) -> QColor:
        """Return a lighter accent color."""
        return self.accent.lighter(factor)

    def darker(self, factor: int) -> QColor:
        """Return a darker accent color."""
        return self.accent.darker(factor)


def request_existing_daemon() -> bool:
    """Ask an already running daemon to show the deck window.

    Returns
    -------
    bool
        ``True`` if a daemon accepted the request, otherwise ``False``.
    """
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(0.08)
            client.connect(str(socket_path()))
            client.sendall(b"show\n")
        return True
    except OSError:
        return False


class PromptDeck(QWidget):
    """Qt widget that displays and controls the prompt deck UI."""

    def __init__(self, config: AppConfig, daemon: bool = False):
        """Create an overlay from resolved config; daemon windows hide on close."""
        super().__init__()
        self.config_path = config.path
        self.decks = config.decks
        self.theme = ThemeColors.from_palette(
            QApplication.palette(), config.appearance.accent
        )
        self.daemon = daemon
        self.deck_index = 0
        self.card_index = 0
        self.selection_visible = False
        self.has_been_active = False
        self.status = ""
        self.server_socket = None
        self.server_notifier = None

        self.setWindowTitle("Prompt Deck")
        self.setWindowFlags(
            Qt.Tool
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)
        self.move_to_cursor_screen()
        self.setWindowOpacity(1.0)

    @property
    def deck(self) -> Deck:
        """Return the currently selected deck.

        Returns
        -------
        Deck
            Deck at ``self.deck_index``.
        """
        return self.decks[self.deck_index]

    @property
    def card(self) -> Card:
        """Return the currently selected card.

        Returns
        -------
        Card
            Card at ``self.card_index`` inside the active deck.
        """
        return self.deck.cards[self.card_index]

    def move_to_cursor_screen(self):
        """Resize the window to the screen under the mouse cursor."""
        screen = (
            QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        )
        self.setGeometry(screen.availableGeometry())

    def show_deck(self):
        """Reload decks, show the window, and focus it for selection."""
        try:
            config = load_app_config(self.config_path)
            self.decks = config.decks
            self.theme = ThemeColors.from_palette(
                QApplication.palette(), config.appearance.accent
            )
            self.deck_index = 0
            self.card_index = 0
            self.status = ""
        except Exception as exc:
            self.status = f"Load failed: {exc}"
        self.has_been_active = False
        self.move_to_cursor_screen()
        self.show()
        self.raise_()
        self.activateWindow()
        self.selection_visible = True
        self.update()

    def start_server(self):
        """Start the local socket server used by daemon mode."""
        path = socket_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()

        self.server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server_socket.setblocking(False)
        self.server_socket.bind(str(path))
        if not IS_WINDOWS:
            os.chmod(path, 0o600)
        self.server_socket.listen(8)

        self.server_notifier = QSocketNotifier(
            self.server_socket.fileno(), QSocketNotifier.Read, self
        )
        self.server_notifier.activated.connect(self.handle_server_request)

    def handle_server_request(self):
        """Handle pending daemon requests and show the deck window."""
        if self.server_socket is None:
            return
        while True:
            try:
                connection, _ = self.server_socket.accept()
            except BlockingIOError:
                return
            with connection:
                connection.recv(64)
            self.show_deck()

    def keyPressEvent(self, event):
        """Handle keyboard navigation, deck switching, and copying.

        Parameters
        ----------
        event : QKeyEvent
            Qt key press event passed by the window system.
        """
        self.selection_visible = True
        key = event.key()
        if key in (Qt.Key_Escape, Qt.Key_Backspace):
            self.close()
            return
        if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.copy_selected()
            return
        if key in (Qt.Key_Right, Qt.Key_L):
            self.move_selection(1)
            return
        if key in (Qt.Key_Left, Qt.Key_H):
            self.move_selection(-1)
            return
        if key in (Qt.Key_Down, Qt.Key_J):
            self.move_selection(self.grid_dimensions(len(self.deck.cards))[0])
            return
        if key in (Qt.Key_Up, Qt.Key_K):
            self.move_selection(-self.grid_dimensions(len(self.deck.cards))[0])
            return
        if key == Qt.Key_Tab:
            self.switch_deck(-1 if event.modifiers() & Qt.ShiftModifier else 1)
            return

        text = event.text().upper()
        if text:
            if text.isdigit():
                index = 9 if text == "0" else int(text) - 1
                if 0 <= index < len(self.deck.cards):
                    self.card_index = index
                    self.update()
                    return

            matches = [
                i
                for i, card in enumerate(self.deck.cards)
                if card.title.upper().startswith(text) or card.key.upper() == text
            ]
            if matches:
                next_matches = [i for i in matches if i > self.card_index]
                self.card_index = next_matches[0] if next_matches else matches[0]
                self.update()
                return

        super().keyPressEvent(event)

    def changeEvent(self, event):
        """Update selection visibility when window activation changes.

        Parameters
        ----------
        event : QEvent
            Qt change event passed by the window system.
        """
        if event.type() == QEvent.ActivationChange:
            self.selection_visible = self.isActiveWindow()
            self.update()
        super().changeEvent(event)

    def focusOutEvent(self, event):
        """Close after real focus loss, not a denied startup activation.

        Parameters
        ----------
        event : QFocusEvent
            Qt focus event passed by the window system.
        """
        self.selection_visible = False
        self.update()
        if self.has_been_active:
            self.close()
        super().focusOutEvent(event)

    def focusInEvent(self, event):
        """Show selection when the window receives focus.

        Parameters
        ----------
        event : QFocusEvent
            Qt focus event passed by the window system.
        """
        self.has_been_active = True
        self.selection_visible = True
        self.update()
        super().focusInEvent(event)

    def move_selection(self, delta: int):
        """Move the selected card by a signed offset.

        Parameters
        ----------
        delta : int
            Number of card positions to move. Positive moves forward;
            negative moves backward.
        """
        self.card_index = max(0, min(len(self.deck.cards) - 1, self.card_index + delta))
        self.status = ""
        self.update()

    def switch_deck(self, direction: int):
        """Switch to another deck.

        Parameters
        ----------
        direction : int
            Signed deck offset. ``1`` moves to the next deck and ``-1``
            moves to the previous deck.
        """
        self.deck_index = (self.deck_index + direction) % len(self.decks)
        self.card_index = 0
        self.status = ""
        self.update()

    def copy_selected(self):
        """Copy the selected card body to the system clipboard."""
        text = self.card.body
        try:
            QApplication.clipboard().setText(text)
            if not self.daemon and not IS_WINDOWS and shutil.which("wl-copy"):
                subprocess.run(["wl-copy"], input=text, text=True, check=True)
            self.close()
        except Exception as exc:
            self.status = f"Copy failed: {exc}"
            self.update()

    def closeEvent(self, event):
        """Handle close requests, hiding instead of quitting in daemon mode.

        Parameters
        ----------
        event : QCloseEvent
            Qt close event passed by the window system.
        """
        if self.daemon:
            event.ignore()
            self.hide()
            return
        super().closeEvent(event)

    def paintEvent(self, event):
        """Paint the prompt deck window.

        Parameters
        ----------
        event : QPaintEvent
            Qt paint event passed by the window system.
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        self.draw_header(painter)
        self.draw_cards(painter)
        self.draw_status(painter)

    def draw_header(self, painter: QPainter):
        """Draw the active deck name and position."""
        painter.setPen(self.theme.alpha(self.theme.text, 210))
        painter.setFont(QFont("Inter", 13, QFont.DemiBold))
        label = f"{self.deck.name}  ·  {self.deck_index + 1}/{len(self.decks)}"
        painter.drawText(QRectF(0, 12, self.width(), 28), Qt.AlignCenter, label)

    def draw_status(self, painter: QPainter):
        """Draw an error reported by loading or clipboard integration."""
        if not self.status:
            return
        painter.setPen(self.theme.error)
        painter.setFont(QFont("Inter", 12, QFont.DemiBold))
        rect = QRectF(30, self.height() - 38, self.width() - 60, 24)
        painter.drawText(rect, Qt.AlignCenter, self.status)

    def draw_cards(self, painter: QPainter):
        """Draw all cards for the active deck.

        Parameters
        ----------
        painter : QPainter
            Painter used to draw on the widget.
        """
        count = len(self.deck.cards)
        columns, rows = self.grid_dimensions(count)
        margin_x = max(42, self.width() * 0.055)
        margin_y = max(42, self.height() * 0.075)
        gap = max(18, min(self.width(), self.height()) * 0.026)
        tile_w = (self.width() - margin_x * 2 - gap * (columns - 1)) / columns
        tile_h = (self.height() - margin_y * 2 - gap * (rows - 1)) / rows

        for index in range(count):
            row = index // columns
            column = index % columns
            x = margin_x + column * (tile_w + gap)
            y = margin_y + row * (tile_h + gap)
            self.draw_card(painter, index, QRectF(x, y, tile_w, tile_h))

    def grid_dimensions(self, count: int) -> tuple[int, int]:
        """Calculate a grid size for a number of cards.

        Parameters
        ----------
        count : int
            Number of cards to place in the grid.

        Returns
        -------
        tuple[int, int]
            Number of columns and rows.
        """
        aspect = max(0.35, self.width() / max(1, self.height()))
        columns = max(1, math.ceil(math.sqrt(count * aspect)))
        rows = math.ceil(count / columns)
        while columns > 1 and (columns - 1) * rows >= count:
            columns -= 1
            rows = math.ceil(count / columns)
        return columns, rows

    def draw_card(self, painter: QPainter, index: int, rect: QRectF):
        """Draw one card tile.

        Parameters
        ----------
        painter : QPainter
            Painter used to draw on the widget.
        index : int
            Card index inside the active deck.
        rect : QRectF
            Rectangle where the card should be drawn.
        """
        card = self.deck.cards[index]
        selected = self.selection_visible and index == self.card_index
        scale = min(rect.width() / 360, rect.height() / 245)
        pad = 22 * scale
        title_size = min(29, max(16, int(21 * scale)))
        body_size = min(19, max(12, int(14 * scale)))

        if selected:
            fill = QLinearGradient(rect.topLeft(), rect.bottomRight())
            fill.setColorAt(0.0, self.theme.lighter(120))
            fill.setColorAt(0.52, self.theme.accent)
            fill.setColorAt(1.0, self.theme.darker(145))
            border = self.theme.lighter(145)
            title_color = self.theme.selected_text
            body_color = self.theme.alpha(self.theme.selected_text, 225)
        else:
            fill = self.theme.alpha(self.theme.card, 224)
            border = self.theme.alpha(self.theme.muted, 205)
            title_color = self.theme.text
            body_color = self.theme.alpha(self.theme.body_text, 225)

        if selected:
            painter.setPen(QPen(self.theme.alpha(self.theme.accent, 110), 8))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(-4, -4, 4, 4), 15, 15)

        painter.setPen(QPen(border, 3 if selected else 1))
        painter.setBrush(QBrush(fill))
        painter.drawRoundedRect(rect, 12, 12)

        badge_text = str(index + 1 if index < 9 else 0)
        badge = QRectF(
            rect.right() - 46 * scale, rect.top() + 16 * scale, 30 * scale, 26 * scale
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.theme.darker(170) if selected else self.theme.muted)
        painter.drawRoundedRect(badge, 7 * scale, 7 * scale)
        painter.setPen(self.theme.selected_text if selected else self.theme.text)
        painter.setFont(QFont("Inter", max(9, int(12 * scale)), QFont.Bold))
        painter.drawText(badge, Qt.AlignCenter, badge_text)

        title_font = QFont("Inter", title_size, QFont.DemiBold)
        painter.setPen(title_color)
        painter.setFont(title_font)
        title_rect = rect.adjusted(pad, 20 * scale, -58 * scale, 0)
        title_metrics = QFontMetrics(title_font)
        title_lines = self.fit_lines(
            card.title,
            title_metrics,
            title_rect.width(),
            title_metrics.lineSpacing() * 2,
        )
        painter.drawText(title_rect, Qt.AlignTop, "\n".join(title_lines))

        preview = " ".join(card.body.split())
        body_font = QFont("Inter", body_size)
        body_metrics = QFontMetrics(body_font)
        body_top = (
            20 * scale + len(title_lines) * title_metrics.lineSpacing() + 16 * scale
        )
        body_rect = rect.adjusted(pad, body_top, -pad, -20 * scale)
        max_body_lines = 12 if selected else 10
        wrapped = "\n".join(
            self.fit_lines(
                preview,
                body_metrics,
                body_rect.width(),
                body_rect.height(),
                max_lines=max_body_lines,
            )
        )

        painter.setPen(body_color)
        painter.setFont(body_font)
        painter.drawText(body_rect, Qt.AlignTop, wrapped)

    def fit_lines(
        self,
        text: str,
        metrics: QFontMetrics,
        width: float,
        height: float,
        max_lines: int | None = None,
    ) -> list[str]:
        """Wrap text to fit inside a rectangle.

        Parameters
        ----------
        text : str
            Text to wrap.
        metrics : QFontMetrics
            Font metrics used to measure text width and line height.
        width : float
            Maximum line width in pixels.
        height : float
            Maximum text block height in pixels.
        max_lines : int | None
            Optional cap on the number of returned lines.

        Returns
        -------
        list[str]
            Wrapped lines, elided when needed to fit the available space.
        """
        available_lines = max(1, int(height // metrics.lineSpacing()))
        max_lines = (
            available_lines if max_lines is None else min(max_lines, available_lines)
        )
        lines = []

        for paragraph in text.splitlines() or [text]:
            current = ""
            for word in paragraph.split():
                candidate = f"{current} {word}".strip()
                if metrics.horizontalAdvance(candidate) <= width:
                    current = candidate
                    continue
                if current:
                    lines.append(current)
                    current = word
                else:
                    lines.append(metrics.elidedText(word, Qt.ElideRight, int(width)))
                if len(lines) == max_lines:
                    lines[-1] = metrics.elidedText(lines[-1], Qt.ElideRight, int(width))
                    return lines
            if current:
                lines.append(current)
                if len(lines) == max_lines:
                    lines[-1] = metrics.elidedText(lines[-1], Qt.ElideRight, int(width))
                    return lines

        return lines
