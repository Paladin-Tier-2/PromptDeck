"""Native first-run setup window for PromptDeck."""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)


@dataclass(frozen=True)
class SetupChoices:
    """Values selected in the setup window."""

    source: Path | None
    accent: str
    install_service: bool


class SetupDialog(QDialog):
    """Collect migration, accent, and Linux autostart choices in one window."""

    def __init__(
        self,
        source: Path | None,
        accent: str = "system",
        allow_service: bool = False,
    ):
        """Create the setup window with safe defaults."""
        super().__init__()
        self.source = source
        self.accent = accent
        self.setWindowTitle("PromptDeck Setup")
        self.setMinimumWidth(520)

        title = QLabel("Set up PromptDeck")
        title_font = title.font()
        title_font.setPointSize(title_font.pointSize() + 5)
        title_font.setBold(True)
        title.setFont(title_font)

        intro = QLabel(
            "Choose where your prompts come from and how the selected card looks."
        )
        intro.setWordWrap(True)

        prompts_title = QLabel("Prompts")
        prompts_title.setStyleSheet("font-weight: 600")
        self.migrate = QCheckBox()
        self.sample = QLabel("A sample prompt deck will be created.")
        self.source_button = QPushButton()
        self.migrate.setChecked(True)
        self.update_source()
        self.source_button.clicked.connect(self.choose_source)
        privacy = QLabel(
            "Your prompts stay in your PromptDeck config folder and are never uploaded."
        )
        privacy.setWordWrap(True)

        accent_title = QLabel("Selected card color")
        accent_title.setStyleSheet("font-weight: 600")
        self.system_accent = QRadioButton("Use my desktop accent color")
        self.custom_accent = QRadioButton("Choose a color")
        self.system_accent.setChecked(accent == "system")
        self.custom_accent.setChecked(accent != "system")
        if accent == "system":
            self.accent = self.palette().color(QPalette.Accent).name()
        self.color_button = QPushButton()
        self.color_button.clicked.connect(self.choose_color)
        self.custom_accent.clicked.connect(self.choose_color)
        self.custom_accent.toggled.connect(self.color_button.setVisible)
        self.color_button.setVisible(self.custom_accent.isChecked())
        self.update_color_button()

        color_row = QHBoxLayout()
        color_row.addWidget(self.custom_accent)
        color_row.addWidget(self.color_button)
        color_row.addStretch()

        self.service = QCheckBox("Start PromptDeck when I sign in")
        self.service.setChecked(allow_service)
        self.service.setVisible(allow_service)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Save)
        buttons.button(QDialogButtonBox.Save).setText("Finish setup")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(intro)
        layout.addWidget(self.rule())
        layout.addWidget(prompts_title)
        layout.addWidget(self.migrate)
        layout.addWidget(self.sample)
        layout.addWidget(self.source_button, alignment=Qt.AlignLeft)
        layout.addWidget(privacy)
        layout.addSpacing(6)
        layout.addWidget(accent_title)
        layout.addWidget(self.system_accent)
        layout.addLayout(color_row)
        layout.addSpacing(6)
        layout.addWidget(self.service)
        layout.addWidget(self.rule())
        layout.addWidget(buttons)

    def rule(self) -> QFrame:
        """Return a horizontal separator using the active Qt palette."""
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        return line

    def choose_source(self) -> None:
        """Let the user choose an existing root deck file."""
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Choose an existing deck file",
            str(self.source.parent if self.source else Path.home()),
            "TOML files (*.toml)",
        )
        if selected:
            self.source = Path(selected).resolve()
            self.migrate.setChecked(True)
            self.update_source()

    def update_source(self) -> None:
        """Update migration text and visibility for the selected source."""
        if self.source:
            self.migrate.setText(f"Copy existing prompts from\n{self.source}")
            self.migrate.setEnabled(True)
            self.migrate.setVisible(True)
            self.sample.setVisible(False)
            self.source_button.setText("Choose a different prompt file...")
        else:
            self.migrate.setVisible(False)
            self.sample.setVisible(True)
            self.source_button.setText("Import an existing prompt file...")

    def choose_color(self) -> None:
        """Open Qt's color picker and keep the chosen accent."""
        color = QColorDialog.getColor(QColor(self.accent), self, "PromptDeck Accent")
        if color.isValid():
            self.accent = color.name()
            self.custom_accent.setChecked(True)
            self.update_color_button()

    def update_color_button(self) -> None:
        """Update the color swatch and its hex label."""
        color = QColor(self.accent)
        text = "#000000" if color.lightnessF() > 0.55 else "#ffffff"
        self.color_button.setText(self.accent)
        self.color_button.setStyleSheet(
            f"background: {self.accent}; color: {text}; padding: 5px 14px"
        )

    def choices(self) -> SetupChoices:
        """Return the current values without writing any files."""
        source = self.source if self.migrate.isChecked() else None
        accent = "system" if self.system_accent.isChecked() else self.accent
        return SetupChoices(source, accent, self.service.isChecked())
