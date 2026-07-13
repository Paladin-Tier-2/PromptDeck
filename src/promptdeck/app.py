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

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QRectF,
    QSocketNotifier,
    Qt,
    QVariantAnimation,
)
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

from .config import AppConfig, Appearance, Card, Deck, load_app_config

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

    text: QColor
    body_text: QColor
    card: QColor
    muted: QColor
    accent: QColor
    selected_border: QColor
    selected_text: QColor
    error: QColor

    @classmethod
    def from_palette(
        cls, palette: QPalette, appearance: Appearance = Appearance()
    ) -> "ThemeColors":
        """Build overlay colors from a Qt palette and appearance settings.

        Parameters
        ----------
        palette : QPalette
            Desktop palette used for every ``system`` value.
        appearance : Appearance, optional
            User color overrides.

        Returns
        -------
        ThemeColors
            Resolved colors ready for painting.
        """
        def color(value: str, role: QPalette.ColorRole) -> QColor:
            return palette.color(role) if value == "system" else QColor(value)

        accent = color(appearance.selected_background, QPalette.Accent)
        luminance = (
            0.2126 * accent.red()
            + 0.7152 * accent.green()
            + 0.0722 * accent.blue()
        ) / 255
        selected_text = QColor("#000000" if luminance > 0.55 else "#ffffff")
        return cls(
            color(appearance.card_text, QPalette.WindowText),
            color(appearance.card_text, QPalette.Text),
            color(appearance.card_background, QPalette.Button),
            color(appearance.card_border, QPalette.Mid),
            accent,
            color(appearance.selected_border, QPalette.Accent),
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

    def __init__(
        self,
        config: AppConfig,
        daemon: bool = False,
        parent: QWidget | None = None,
        embedded: bool = False,
    ):
        """Create a full overlay or an embedded setup preview.

        Parameters
        ----------
        config : AppConfig
            Resolved decks and appearance settings.
        daemon : bool, optional
            Hide instead of quitting when the window closes.
        parent : QWidget or None, optional
            Parent widget used by the setup preview.
        embedded : bool, optional
            Draw inside setup instead of creating a top-level overlay.
        """
        super().__init__(parent)
        self.config_path = config.path
        self.decks = config.decks
        self.theme = ThemeColors.from_palette(
            QApplication.palette(), config.appearance
        )
        self.daemon = daemon
        self.embedded = embedded
        self.deck_index = 0
        self.card_index = 0
        self.deck_finder_open = False
        self.deck_query = ""
        self.deck_result_index = 0
        self.deck_finder_progress = 0.0
        self.deck_finder_animation = QVariantAnimation(self)
        self.deck_finder_animation.setDuration(120)
        self.deck_finder_animation.setEasingCurve(QEasingCurve.OutCubic)
        self.deck_finder_animation.valueChanged.connect(
            self.set_deck_finder_progress
        )
        self.deck_finder_animation.finished.connect(
            self.finish_deck_finder_animation
        )
        self.selection_visible = False
        self.has_been_active = False
        self.status = ""
        self.server_socket = None
        self.server_notifier = None

        if embedded:
            self.setFocusPolicy(Qt.NoFocus)
        else:
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
                QApplication.palette(), config.appearance
            )
            self.deck_index = 0
            self.card_index = 0
            self.status = ""
        except Exception as exc:
            self.status = f"Load failed: {exc}"
        self.deck_finder_open = False
        self.deck_query = ""
        self.deck_result_index = 0
        self.deck_finder_animation.stop()
        self.deck_finder_progress = 0.0
        self.has_been_active = False
        self.move_to_cursor_screen()
        self.show()
        self.raise_()
        self.activateWindow()
        self.selection_visible = True
        self.update()

    def set_appearance(self, appearance: Appearance) -> None:
        """Apply appearance settings to the overlay renderer.

        Parameters
        ----------
        appearance : Appearance
            Values to resolve against the active desktop palette.
        """
        self.theme = ThemeColors.from_palette(QApplication.palette(), appearance)
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
        if self.deck_finder_open:
            self.handle_deck_finder_key(event)
            return
        if key == Qt.Key_Slash or event.text() == "/":
            self.open_deck_finder()
            return
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

    @property
    def matching_deck_indices(self) -> list[int]:
        """Return deck indices matching the current finder query.

        Returns
        -------
        list[int]
            Matching deck indices in configured order.
        """
        query = self.deck_query.strip().casefold()
        if not query:
            return list(range(len(self.decks)))
        return [
            index
            for index, deck in enumerate(self.decks)
            if query in deck.name.casefold()
        ]

    def open_deck_finder(self) -> None:
        """Open the finder with the current deck highlighted."""
        self.deck_finder_open = True
        self.deck_query = ""
        self.deck_result_index = self.deck_index
        self.animate_deck_finder(1.0)

    def close_deck_finder(self) -> None:
        """Close the finder without changing the current card."""
        self.deck_finder_open = False
        self.animate_deck_finder(0.0)

    def animate_deck_finder(self, end: float) -> None:
        """Animate between the card view and finder.

        Parameters
        ----------
        end : float
            Target progress, where zero is cards and one is the finder.
        """
        self.deck_finder_animation.stop()
        self.deck_finder_animation.setStartValue(self.deck_finder_progress)
        self.deck_finder_animation.setEndValue(end)
        self.deck_finder_animation.start()

    def set_deck_finder_progress(self, value: float) -> None:
        """Apply an animation value and repaint the overlay.

        Parameters
        ----------
        value : float
            Current animation progress from zero to one.
        """
        self.deck_finder_progress = float(value)
        self.update()

    def finish_deck_finder_animation(self) -> None:
        """Clear finder text after its closing frame has disappeared."""
        if not self.deck_finder_open:
            self.deck_query = ""
            self.deck_result_index = 0
            self.deck_finder_progress = 0.0
            self.update()

    def move_deck_result(self, delta: int) -> None:
        """Move the finder selection by a signed offset.

        Parameters
        ----------
        delta : int
            Positive values move forward and negative values move backward.
        """
        matches = self.matching_deck_indices
        if matches:
            self.deck_result_index = (self.deck_result_index + delta) % len(matches)
            self.update()

    def handle_deck_finder_key(self, event) -> None:
        """Handle one key while the deck finder is active.

        Parameters
        ----------
        event : QKeyEvent
            Qt key press event passed by the window system.
        """
        key = event.key()
        if key == Qt.Key_Escape:
            self.close_deck_finder()
            return
        if key == Qt.Key_Backspace:
            if not self.deck_query:
                self.close_deck_finder()
                return
            self.deck_query = self.deck_query[:-1]
            self.deck_result_index = 0
            self.update()
            return
        if key in (Qt.Key_Return, Qt.Key_Enter):
            matches = self.matching_deck_indices
            if matches:
                self.deck_index = matches[self.deck_result_index]
                self.card_index = 0
                self.status = ""
                self.close_deck_finder()
            return
        if key == Qt.Key_Tab:
            direction = -1 if event.modifiers() & Qt.ShiftModifier else 1
            self.move_deck_result(direction)
            return
        if key in (Qt.Key_Left, Qt.Key_Up):
            self.move_deck_result(-1)
            return
        if key in (Qt.Key_Right, Qt.Key_Down):
            self.move_deck_result(1)
            return

        blocked = Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier
        text = event.text()
        if text and text.isprintable() and not event.modifiers() & blocked:
            self.deck_query += text
            self.deck_result_index = 0
            self.update()

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
        if self.embedded:
            self.selection_visible = True
            self.update()
            super().focusOutEvent(event)
            return
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

        card_opacity = max(0.0, 1.0 - self.deck_finder_progress)
        if card_opacity:
            painter.save()
            painter.setOpacity(card_opacity)
            if not self.embedded:
                self.draw_header(painter)
            self.draw_cards(painter)
            self.draw_status(painter)
            painter.restore()
        if self.deck_finder_progress:
            self.draw_deck_finder(painter, self.deck_finder_progress)

    def draw_header(self, painter: QPainter):
        """Draw the active deck name and position."""
        font = QFont("Inter", 13, QFont.DemiBold)
        painter.setFont(font)
        label = f"{self.deck.name}  ·  {self.deck_index + 1}/{len(self.decks)}"
        width = QFontMetrics(font).horizontalAdvance(label) + 28
        pill = QRectF((self.width() - width) / 2, 8, width, 34)
        painter.setPen(QPen(self.theme.alpha(self.theme.muted, 190), 1))
        painter.setBrush(self.theme.alpha(self.theme.card, 240))
        painter.drawRoundedRect(pill, 10, 10)
        painter.setPen(self.theme.alpha(self.theme.text, 225))
        painter.drawText(pill, Qt.AlignCenter, label)

    def draw_status(self, painter: QPainter):
        """Draw an error reported by loading or clipboard integration."""
        if not self.status:
            return
        painter.setPen(self.theme.error)
        painter.setFont(QFont("Inter", 12, QFont.DemiBold))
        rect = QRectF(30, self.height() - 38, self.width() - 60, 24)
        painter.drawText(rect, Qt.AlignCenter, self.status)

    def draw_deck_finder(self, painter: QPainter, progress: float) -> None:
        """Draw the temporary centered deck finder.

        Parameters
        ----------
        painter : QPainter
            Painter used to draw on the overlay.
        progress : float
            Finder transition progress from zero to one.
        """
        painter.save()
        backdrop = QColor(self.theme.card).darker(180)
        backdrop.setAlpha(int(245 * progress))
        painter.fillRect(self.rect(), backdrop)
        painter.setOpacity(progress)

        matches = self.matching_deck_indices
        row_height = 54.0
        max_rows = max(1, min(7, int((self.height() - 160) / row_height)))
        visible_count = min(max_rows, len(matches))
        displayed_rows = max(1, visible_count)
        panel_width = max(280.0, min(680.0, self.width() - 48.0))
        panel_height = 78.0 + displayed_rows * row_height + 14.0
        top = max(36.0, (self.height() - panel_height) / 2)
        panel = QRectF(
            (self.width() - panel_width) / 2,
            top,
            panel_width,
            panel_height,
        )

        painter.setPen(QPen(self.theme.alpha(self.theme.muted, 220), 1))
        painter.setBrush(self.theme.alpha(self.theme.card, 250))
        painter.drawRoundedRect(panel, 13, 13)

        search = panel.adjusted(14, 14, -14, 0)
        search.setHeight(48)
        painter.setPen(QPen(self.theme.alpha(self.theme.muted, 210), 1))
        painter.setBrush(self.theme.alpha(self.theme.card, 255))
        painter.drawRoundedRect(search, 9, 9)
        painter.setFont(QFont("Inter", 14, QFont.DemiBold))
        painter.setPen(
            self.theme.text
            if self.deck_query
            else self.theme.alpha(self.theme.body_text, 150)
        )
        search_text = self.deck_query if self.deck_query else "Find a deck..."
        painter.drawText(search.adjusted(16, 0, -54, 0), Qt.AlignVCenter, search_text)
        painter.setFont(QFont("Inter", 11, QFont.DemiBold))
        painter.setPen(self.theme.alpha(self.theme.body_text, 155))
        painter.drawText(
            search.adjusted(0, 0, -14, 0),
            Qt.AlignVCenter | Qt.AlignRight,
            str(len(matches)),
        )

        results_top = search.bottom() + 8
        if not matches:
            painter.setFont(QFont("Inter", 13))
            painter.setPen(self.theme.alpha(self.theme.body_text, 190))
            message = f'No decks match "{self.deck_query}"'
            painter.drawText(
                QRectF(panel.left() + 20, results_top, panel.width() - 40, row_height),
                Qt.AlignCenter,
                message,
            )
            painter.restore()
            return

        start = max(
            0,
            min(
                self.deck_result_index - visible_count // 2,
                len(matches) - visible_count,
            ),
        )
        for visible_index, match_position in enumerate(
            range(start, start + visible_count)
        ):
            deck_index = matches[match_position]
            deck = self.decks[deck_index]
            row = QRectF(
                panel.left() + 14,
                results_top + visible_index * row_height,
                panel.width() - 28,
                row_height - 3,
            )
            selected = match_position == self.deck_result_index
            if selected:
                painter.setPen(QPen(self.theme.selected_border, 2))
                painter.setBrush(self.theme.accent)
                painter.drawRoundedRect(row, 8, 8)
                text_color = self.theme.selected_text
            else:
                painter.setPen(QPen(self.theme.alpha(self.theme.muted, 95), 1))
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(row, 8, 8)
                text_color = self.theme.text

            painter.setPen(text_color)
            painter.setFont(QFont("Inter", 14, QFont.DemiBold))
            painter.drawText(row.adjusted(16, 0, -170, 0), Qt.AlignVCenter, deck.name)
            count = len(deck.cards)
            meta = f"{count} card" + ("" if count == 1 else "s")
            if deck_index == self.deck_index:
                meta = f"Current  ·  {meta}"
            painter.setFont(QFont("Inter", 10, QFont.DemiBold))
            painter.setPen(self.theme.alpha(text_color, 205))
            painter.drawText(
                row.adjusted(0, 0, -16, 0),
                Qt.AlignVCenter | Qt.AlignRight,
                meta,
            )

        painter.restore()

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
            border = self.theme.selected_border
            title_color = self.theme.selected_text
            body_color = self.theme.alpha(self.theme.selected_text, 225)
        else:
            fill = self.theme.alpha(self.theme.card, 224)
            border = self.theme.alpha(self.theme.muted, 205)
            title_color = self.theme.text
            body_color = self.theme.alpha(self.theme.body_text, 225)

        if selected:
            painter.setPen(QPen(self.theme.alpha(self.theme.selected_border, 110), 8))
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
