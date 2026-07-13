import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from promptdeck.app import QApplication, PromptDeck  # noqa: E402
from promptdeck.config import AppConfig, Appearance, Card, Deck  # noqa: E402


def demo_decks() -> list[Deck]:
    return [
        Deck(
            "Writing",
            [
                Card("Make concise", "Make this shorter without changing its meaning.\n", "C"),
                Card("Check clarity", "Find unclear wording and explain what makes it hard to follow.\n", "R"),
                Card("Keep my voice", "Revise this while preserving the way I naturally speak.\n", "V"),
                Card("Strong opening", "Give this a direct opening that earns attention.\n", "O"),
                Card("Remove filler", "Cut filler, repetition, and claims the evidence cannot support.\n", "F"),
                Card("Final pass", "Check the final version for tone, logic, and small mistakes.\n", "P"),
            ],
        ),
        Deck(
            "Code",
            [
                Card("Explain error", "Explain the cause, then show the smallest useful fix.\n", "E"),
                Card("Review diff", "Review this diff for correctness, clarity, and unnecessary complexity.\n", "D"),
                Card("Write test", "Write one behavior-focused test for this failure mode.\n", "T"),
                Card("Trace data", "Trace this value from input to its final consumer.\n", "A"),
            ],
        ),
    ]


def save_frames(widget: PromptDeck, directory: Path):
    frame = 0

    def hold(count: int):
        nonlocal frame
        for _ in range(count):
            QApplication.processEvents()
            pixmap = widget.grab()
            image = QImage(pixmap.size(), QImage.Format_RGB32)
            image.fill(QColor("#0b0f14"))
            painter = QPainter(image)
            painter.drawPixmap(0, 0, pixmap)
            painter.end()
            image.save(str(directory / f"frame-{frame:03d}.png"))
            frame += 1

    hold(10)
    for _ in range(3):
        QTest.keyClick(widget, Qt.Key_Right)
        hold(8)
    QTest.keyClick(widget, Qt.Key_Down)
    hold(10)
    QTest.keyClick(widget, Qt.Key_Tab)
    hold(12)
    QTest.keyClick(widget, Qt.Key_Right)
    hold(9)
    QTest.keyClick(widget, Qt.Key_Right)
    hold(12)


def main():
    app = QApplication([])
    source = Path("unused.toml")
    widget = PromptDeck(AppConfig(source, source, Appearance(), demo_decks()))
    widget.setGeometry(0, 0, 960, 540)
    widget.selection_visible = True
    widget.show()
    widget.activateWindow()

    output = REPO / "assets" / "promptdeck-demo.gif"
    output.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="promptdeck-demo-") as directory:
        frames = Path(directory)
        save_frames(widget, frames)
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-framerate",
                "10",
                "-i",
                str(frames / "frame-%03d.png"),
                "-vf",
                "fps=8,scale=720:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=96[p];[s1][p]paletteuse=dither=bayer",
                "-loop",
                "0",
                str(output),
            ],
            check=True,
        )
    print(output)


if __name__ == "__main__":
    main()
