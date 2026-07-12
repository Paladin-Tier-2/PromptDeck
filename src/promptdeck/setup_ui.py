"""Native first-run setup window for PromptDeck."""

from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .app import PromptDeck
from .config import (
    APPEARANCE_COLOR_KEYS,
    AppConfig,
    Appearance,
    Card,
    Deck,
    appearance_toml,
)


@dataclass(frozen=True)
class SetupChoices:
    """Values selected in the setup window.

    Attributes
    ----------
    source : pathlib.Path or None
        Existing deck file to copy, if migration is enabled.
    appearance : Appearance
        Colors selected on the appearance page.
    install_service : bool
        Whether setup should enable Linux user autostart.
    """

    source: Path | None
    appearance: Appearance
    install_service: bool


class SetupDialog(QDialog):
    """Collect prompt, appearance, and Linux autostart choices."""

    COLOR_ROLES = {
        "accent": QPalette.Accent,
        "card_background": QPalette.Button,
        "card_border": QPalette.Mid,
        "selected_border": QPalette.Accent,
        "card_text": QPalette.WindowText,
    }
    COLOR_HELP = {
        "accent": "Selected card fill",
        "card_background": "Other card fill",
        "card_border": "Other card outline",
        "selected_border": "Selected card outline",
        "card_text": "Other card text",
    }

    def __init__(
        self,
        source: Path | None,
        appearance: Appearance = Appearance(),
        allow_service: bool = False,
    ):
        """Create the two-page setup window.

        Parameters
        ----------
        source : pathlib.Path or None
            Existing deck file offered for migration.
        appearance : Appearance, optional
            Initial values shown by the appearance controls.
        allow_service : bool, optional
            Show Linux user-service controls when ``True``.
        """
        super().__init__()
        self.source = source
        self.appearance = appearance
        self.setWindowTitle("PromptDeck Setup")
        self.setMinimumSize(1120, 650)

        self.migrate = QCheckBox()
        self.migrate.setChecked(True)
        self.sample = QLabel("A sample prompt deck will be created.")
        self.source_button = QPushButton()
        self.source_button.clicked.connect(self.choose_source)
        self.update_source()

        self.service = QCheckBox("Start PromptDeck when I sign in")
        self.service.setChecked(allow_service)
        self.service.setVisible(allow_service)

        self.color_buttons: dict[str, QPushButton] = {}
        self.system_buttons: dict[str, QPushButton] = {}
        self.toml = QPlainTextEdit()
        self.toml.setReadOnly(True)
        self.toml.setMaximumHeight(180)
        self.toml.setLineWrapMode(QPlainTextEdit.NoWrap)

        preview_config = AppConfig(
            Path(),
            Path(),
            appearance,
            [
                Deck(
                    "Preview",
                    [
                        Card("Selected prompt", "The selected colors change here.\n"),
                        Card("Another prompt", "The card colors change here.\n"),
                        Card("Keyboard first", "Use arrows or H/J/K/L to move.\n"),
                        Card("Copy and close", "Press Enter to copy the prompt.\n"),
                    ],
                )
            ],
        )
        self.preview = PromptDeck(preview_config, parent=self, embedded=True)
        self.preview.setMinimumSize(680, 520)
        self.preview.selection_visible = True

        self.pages = QStackedWidget()
        self.pages.addWidget(self.prompt_page())
        self.pages.addWidget(self.appearance_page())

        self.back_button = QPushButton("Back")
        self.next_button = QPushButton("Next")
        self.finish_button = QPushButton("Finish setup")
        cancel_button = QPushButton("Cancel")
        self.back_button.clicked.connect(lambda: self.show_page(0))
        self.next_button.clicked.connect(lambda: self.show_page(1))
        self.finish_button.clicked.connect(self.accept)
        cancel_button.clicked.connect(self.reject)

        navigation = QHBoxLayout()
        navigation.addWidget(cancel_button)
        navigation.addStretch()
        navigation.addWidget(self.back_button)
        navigation.addWidget(self.next_button)
        navigation.addWidget(self.finish_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.addWidget(self.pages)
        layout.addWidget(self.rule())
        layout.addLayout(navigation)

        self.update_preview()
        self.show_page(0)

    def prompt_page(self) -> QWidget:
        """Build the prompt import and autostart page.

        Returns
        -------
        QWidget
            First page of the setup flow.
        """
        page = QWidget()
        content = QFrame()
        content.setMaximumWidth(680)
        layout = QVBoxLayout(content)
        layout.setSpacing(14)
        layout.addWidget(self.heading("Set up PromptDeck"))
        intro = QLabel("Choose where PromptDeck gets its prompts.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addWidget(self.rule())
        layout.addWidget(self.migrate)
        layout.addWidget(self.sample)
        layout.addWidget(self.source_button, alignment=Qt.AlignLeft)
        privacy = QLabel(
            "Your prompts stay in your PromptDeck config folder and are never uploaded."
        )
        privacy.setWordWrap(True)
        layout.addWidget(privacy)
        layout.addSpacing(10)
        layout.addWidget(self.service)
        layout.addStretch()

        outer = QHBoxLayout(page)
        outer.addStretch()
        outer.addWidget(content)
        outer.addStretch()
        return page

    def appearance_page(self) -> QWidget:
        """Build the live overlay preview and appearance controls.

        Returns
        -------
        QWidget
            Second page of the setup flow.
        """
        page = QWidget()
        preview_panel = QFrame()
        preview_panel.setFrameShape(QFrame.StyledPanel)
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(8, 8, 8, 8)
        preview_layout.addWidget(self.preview)

        settings = QFrame()
        settings_layout = QVBoxLayout(settings)
        settings_layout.setContentsMargins(20, 8, 8, 8)
        settings_layout.setSpacing(10)
        settings_layout.addWidget(self.heading("Appearance"))
        help_text = QLabel(
            "Click a value to choose a color. Use system to follow your desktop theme."
        )
        help_text.setWordWrap(True)
        settings_layout.addWidget(help_text)
        settings_layout.addWidget(self.rule())

        for key in APPEARANCE_COLOR_KEYS:
            row = QHBoxLayout()
            label = QLabel(key)
            label.setMinimumWidth(145)
            label.setStyleSheet("font-family: monospace; font-weight: 600")
            label.setToolTip(self.COLOR_HELP[key])
            color_button = QPushButton()
            color_button.clicked.connect(
                lambda checked=False, name=key: self.choose_color(name)
            )
            system_button = QPushButton("Use system")
            system_button.clicked.connect(
                lambda checked=False, name=key: self.use_system_color(name)
            )
            self.color_buttons[key] = color_button
            self.system_buttons[key] = system_button
            row.addWidget(label)
            row.addWidget(color_button, 1)
            row.addWidget(system_button)
            settings_layout.addLayout(row)

        toml_label = QLabel("config.toml")
        toml_label.setStyleSheet("font-family: monospace; font-weight: 600")
        settings_layout.addSpacing(4)
        settings_layout.addWidget(toml_label)
        settings_layout.addWidget(self.toml)
        settings_layout.addStretch()

        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(preview_panel, 3)
        layout.addWidget(settings, 2)
        return page

    def heading(self, text: str) -> QLabel:
        """Create a large page heading.

        Parameters
        ----------
        text : str
            Heading text.

        Returns
        -------
        QLabel
            Styled label containing ``text``.
        """
        label = QLabel(text)
        font = label.font()
        font.setPointSize(font.pointSize() + 5)
        font.setBold(True)
        label.setFont(font)
        return label

    def rule(self) -> QFrame:
        """Create a horizontal separator.

        Returns
        -------
        QFrame
            Separator using the active Qt palette.
        """
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        return line

    def show_page(self, index: int) -> None:
        """Show one setup page and its navigation buttons.

        Parameters
        ----------
        index : int
            Page index, either ``0`` for prompts or ``1`` for appearance.
        """
        self.pages.setCurrentIndex(index)
        self.back_button.setVisible(index == 1)
        self.next_button.setVisible(index == 0)
        self.finish_button.setVisible(index == 1)

    def choose_source(self) -> None:
        """Open a file dialog for an existing root deck file."""
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

    def choose_color(self, key: str) -> None:
        """Open a picker and preview one setting while it is open.

        Parameters
        ----------
        key : str
            Appearance key controlled by the picker.
        """
        previous = self.appearance
        value = getattr(previous, key)
        initial = (
            self.palette().color(self.COLOR_ROLES[key])
            if value == "system"
            else QColor(value)
        )
        dialog = QColorDialog(initial, self)
        dialog.setWindowTitle(key)
        dialog.currentColorChanged.connect(
            lambda color: self.preview_color(key, color)
        )
        if dialog.exec() != QDialog.Accepted:
            self.appearance = previous
            self.update_preview()

    def preview_color(self, key: str, color: QColor) -> None:
        """Apply a picker color to the config and overlay preview.

        Parameters
        ----------
        key : str
            Appearance key to update.
        color : QColor
            Current color emitted by the open picker.
        """
        if color.isValid():
            self.appearance = replace(self.appearance, **{key: color.name()})
            self.update_preview()

    def use_system_color(self, key: str) -> None:
        """Reset one setting to the desktop palette.

        Parameters
        ----------
        key : str
            Appearance key to reset to ``system``.
        """
        self.appearance = replace(self.appearance, **{key: "system"})
        self.update_preview()

    def update_preview(self) -> None:
        """Update the overlay, color buttons, and matching TOML."""
        self.preview.set_appearance(self.appearance)
        self.preview.selection_visible = True
        self.toml.setPlainText(appearance_toml(self.appearance))
        for key, button in self.color_buttons.items():
            value = getattr(self.appearance, key)
            color = (
                self.palette().color(self.COLOR_ROLES[key])
                if value == "system"
                else QColor(value)
            )
            text = "#000000" if color.lightnessF() > 0.55 else "#ffffff"
            button.setText(value)
            button.setStyleSheet(
                f"background: {color.name()}; color: {text}; padding: 5px 10px"
            )
            self.system_buttons[key].setEnabled(value != "system")
        self.preview.update()

    def choices(self) -> SetupChoices:
        """Return the current values without writing files.

        Returns
        -------
        SetupChoices
            Prompt source, appearance, and autostart choices.
        """
        source = self.source if self.migrate.isChecked() else None
        return SetupChoices(source, self.appearance, self.service.isChecked())
