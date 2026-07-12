/home/eko/.bashrc: line 104: bind: warning: line editing not enabled
#!/usr/bin/env python3
import argparse
import math
import os
import socket
import subprocess
import sys
import tempfile
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
    QPen,
)
from PySide6.QtWidgets import QApplication, QWidget

from deck_config import Card, Deck, DeckConfigError, load_decks

IS_WINDOWS = sys.platform == "win32"
SOURCE = Path(__file__).resolve().parent / "decks.toml"
LEGACY_SOURCE = Path.home() / ".config" / "prompt-deck" / "decks.toml"
if IS_WINDOWS:
    RUNTIME_DIR = Path(tempfile.gettempdir())
else:
    RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
SOCKET = RUNTIME_DIR / "prompt-deck.sock"


def deck_source(config: Path | None = None) -> Path:
    """Return the TOML file used as the deck source.

    Returns
    -------
    Path
        ``SOURCE`` when it exists, otherwise ``LEGACY_SOURCE`` when it
        exists, otherwise ``SOURCE`` as the default path.
    """
    if config is not None:
        return config.expanduser().resolve()
    if SOURCE.exists():
        return SOURCE
    if LEGACY_SOURCE.exists():
        return LEGACY_SOURCE
    return SOURCE


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
            client.connect(str(SOCKET))
            client.sendall(b"show\n")
        return True
    except OSError:
        return False


class PromptDeck(QWidget):
    """Qt widget that displays and controls the prompt deck UI."""

    def __init__(self, decks: list[Deck], source: Path, daemon: bool = False):
        """Create the prompt deck window.

        Parameters
        ----------
        decks : list[Deck]
            Decks available in the UI.
        source : Path
            TOML file reloaded each time the window opens.
        daemon : bool
            When ``True``, closing the window hides it instead of quitting.
        """
        super().__init__()
        self.decks = decks
        self.source = source
        self.daemon = daemon
        self.deck_index = 0
        self.card_index = 0
        self.selection_visible = False
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
            self.decks = load_decks(self.source)
            self.deck_index = 0
            self.card_index = 0
            self.status = ""
        except Exception as exc:
            self.status = f"Load failed: {exc}"
        self.move_to_cursor_screen()
        self.show()
        self.raise_()
        self.activateWindow()
        self.selection_visible = True
        self.update()

    def start_server(self):
        """Start the local socket server used by daemon mode."""
        SOCKET.parent.mkdir(parents=True, exist_ok=True)
        if SOCKET.exists():
            SOCKET.unlink()

        self.server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server_socket.setblocking(False)
        self.server_socket.bind(str(SOCKET))
        if not IS_WINDOWS:
            os.chmod(SOCKET, 0o600)
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
        """Hide selection and close the window when focus is lost.

        Parameters
        ----------
        event : QFocusEvent
            Qt focus event passed by the window system.
        """
        self.selection_visible = False
        self.update()
        self.close()
        super().focusOutEvent(event)

    def focusInEvent(self, event):
        """Show selection when the window receives focus.

        Parameters
        ----------
        event : QFocusEvent
            Qt focus event passed by the window system.
        """
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
            if IS_WINDOWS:
                QApplication.clipboard().setText(text)
                self.close()
                return

            subprocess.run(["wl-copy"], input=text, text=True, check=True)
            subprocess.Popen(
                ["notify-send", "Prompt Deck", f"Copied: {self.card.title}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
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
        painter.setPen(QColor(220, 230, 242, 210))
        painter.setFont(QFont("Inter", 13, QFont.DemiBold))
        label = f"{self.deck.name}  ·  {self.deck_index + 1}/{len(self.decks)}"
        painter.drawText(QRectF(0, 12, self.width(), 28), Qt.AlignCenter, label)

    def draw_status(self, painter: QPainter):
        """Draw an error reported by loading or clipboard integration."""
        if not self.status:
            return
        painter.setPen(QColor("#ffb4ab"))
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
            fill.setColorAt(0.0, QColor("#3daee9"))
            fill.setColorAt(0.52, QColor("#2f8fbd"))
            fill.setColorAt(1.0, QColor("#1f5f82"))
            border = QColor("#9ad9ff")
            title_color = QColor("#06111a")
            body_color = QColor("#071722")
        else:
            fill = QColor(0, 0, 0, 224)
            border = QColor(92, 110, 130, 205)
            title_color = QColor("#ffffff")
            body_color = QColor(235, 242, 250, 225)

        if selected:
            painter.setPen(QPen(QColor(61, 174, 233, 110), 8))
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
        painter.setBrush(QColor("#0f172a" if selected else "#334155"))
        painter.drawRoundedRect(badge, 7 * scale, 7 * scale)
        painter.setPen(QColor("#ffffff"))
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


def parse_args(argv: list[str]):
    parser = argparse.ArgumentParser(description="Open a keyboard-first prompt picker.")
    parser.add_argument("--config", type=Path, help="path to the deck TOML file")
    parser.add_argument("--daemon", action="store_true", help="keep PromptDeck warm")
    parser.add_argument(
        "--show", action="store_true", help="show PromptDeck at startup"
    )
    return parser.parse_known_args(argv)


def main():
    """Run the Prompt Deck application.

    Returns
    -------
    int
        Qt application exit code, or ``0`` when an existing daemon handled
        the request.
    """
    args, qt_args = parse_args(sys.argv[1:])
    if not args.daemon and args.config is None and request_existing_daemon():
        return 0

    source = deck_source(args.config)
    try:
        decks = load_decks(source)
    except DeckConfigError as exc:
        print(f"PromptDeck: {exc}", file=sys.stderr)
        return 2

    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("prompt-deck")
    app.setApplicationDisplayName("Prompt Deck")
    app.setDesktopFileName("net.local.prompt-deck")
    app.setQuitOnLastWindowClosed(not args.daemon)

    widget = PromptDeck(decks, source=source, daemon=args.daemon)
    if args.daemon:
        widget.start_server()
        if args.show:
            widget.show_deck()
    else:
        widget.show_deck()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
