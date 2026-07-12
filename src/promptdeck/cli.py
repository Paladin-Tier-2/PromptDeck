"""Command-line entry point, first-run setup, and Linux service controls."""

import argparse
import os
import signal
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from .config import (
    APPEARANCE_COLOR_KEYS,
    Appearance,
    DeckConfigError,
    appearance_toml,
    config_dir,
    config_path,
    load_app_config,
    valid_color,
)


SAMPLE_DECKS = '''[[decks]]
name = "Writing"

[[decks.cards]]
title = "Make concise"
key = "C"
body = "Make this shorter without changing its meaning."

[[decks.cards]]
title = "Check clarity"
key = "R"
body = "Review this text for unclear wording before suggesting a revision."
'''


def parser() -> argparse.ArgumentParser:
    """Build the public command-line interface."""
    result = argparse.ArgumentParser(
        prog="promptdeck", description="Open a keyboard-first prompt picker."
    )
    result.add_argument("--config", type=Path, help="config.toml or a deck TOML file")
    commands = result.add_subparsers(dest="command")
    commands.add_parser("daemon", help="run the warm foreground daemon")
    setup = commands.add_parser(
        "setup", help="create config and optional Linux integration"
    )
    setup.add_argument(
        "--yes", action="store_true", help="accept safe defaults without prompting"
    )
    setup.add_argument(
        "--no-service", action="store_true", help="do not install the Linux user service"
    )
    setup.add_argument("--accent", default=None, help="system or #RRGGBB")
    setup.add_argument(
        "--migrate",
        type=Path,
        help="copy an existing decks.toml and sibling decks directory",
    )
    setup.add_argument(
        "--terminal", action="store_true", help="use terminal prompts instead of Qt dialogs"
    )
    service = commands.add_parser("service", help="manage the Linux user service")
    service.add_argument(
        "action",
        choices=("install", "start", "stop", "restart", "status", "uninstall"),
    )
    return result


def main(argv: list[str] | None = None) -> int:
    """Run a CLI command or open the PromptDeck overlay."""
    args, qt_args = parser().parse_known_args(argv)
    if args.command == "setup":
        return setup(args, qt_args)
    if args.command == "service":
        return service(args.action)

    from PySide6.QtCore import QTimer

    from .app import QApplication, PromptDeck, request_existing_daemon

    path = config_path(args.config)
    if args.command is None and args.config is None and request_existing_daemon():
        return 0
    try:
        config = load_app_config(path)
    except DeckConfigError as exc:
        print(f"PromptDeck: {exc}\nRun 'promptdeck setup' first.", file=sys.stderr)
        return 2

    app = QApplication(["promptdeck", *qt_args])
    app.setApplicationName("promptdeck")
    app.setApplicationDisplayName("PromptDeck")
    app.setDesktopFileName("promptdeck")
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    signal_timer = QTimer()
    signal_timer.timeout.connect(lambda: None)
    signal_timer.start(250)
    daemon = args.command == "daemon"
    app.setQuitOnLastWindowClosed(not daemon)
    widget = PromptDeck(config, daemon=daemon)
    if daemon:
        widget.start_server()
    else:
        widget.show_deck()
    return app.exec()


def setup(args: argparse.Namespace, qt_args: list[str] | None = None) -> int:
    """Run graphical, terminal, or unattended setup.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed PromptDeck setup options.
    qt_args : list of str or None, optional
        Unknown command-line values forwarded to Qt.

    Returns
    -------
    int
        Process exit code.
    """
    source = args.migrate.expanduser().resolve() if args.migrate else detect_legacy()
    if args.yes:
        service_choice = (
            True
            if sys.platform.startswith("linux") and not args.no_service
            else None
        )
        return finish_setup(
            source,
            Appearance(accent=args.accent or "system"),
            args.accent is not None,
            service_choice,
        )
    if args.terminal:
        return terminal_setup(args, source)
    install_desktop_entry()
    return graphical_setup(args, source, qt_args or [])


def terminal_setup(args: argparse.Namespace, source: Path | None) -> int:
    """Collect migration and accent choices in the terminal.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed PromptDeck setup options.
    source : pathlib.Path or None
        Existing deck file offered for migration.

    Returns
    -------
    int
        Process exit code from :func:`finish_setup`.
    """
    if source:
        answer = input(f"Copy prompts from {source}? [Y/n] ").strip().lower()
        if answer not in ("", "y", "yes"):
            source = None
    accent = (
        args.accent
        or input("Accent [system or #RRGGBB] (system): ").strip()
        or "system"
    )
    service_choice = (
        True if sys.platform.startswith("linux") and not args.no_service else None
    )
    return finish_setup(source, Appearance(accent=accent), True, service_choice)


def graphical_setup(
    args: argparse.Namespace, source: Path | None, qt_args: list[str]
) -> int:
    """Collect setup choices with the native Qt window.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed PromptDeck setup options.
    source : pathlib.Path or None
        Existing deck file offered for migration.
    qt_args : list of str
        Unknown command-line values forwarded to Qt.

    Returns
    -------
    int
        Process exit code from the dialog or :func:`finish_setup`.
    """
    from PySide6.QtWidgets import QApplication, QDialog

    from .setup_ui import SetupDialog

    app = QApplication.instance() or QApplication(["promptdeck-setup", *qt_args])
    app.setApplicationName("promptdeck")
    app.setApplicationDisplayName("PromptDeck Setup")
    app.setDesktopFileName("promptdeck")

    appearance = Appearance()
    settings = config_path(args.config)
    if settings.exists():
        try:
            appearance = load_app_config(settings).appearance
        except DeckConfigError:
            pass
    if args.accent is not None:
        appearance = replace(appearance, accent=args.accent)

    manage_service = sys.platform.startswith("linux") and not args.no_service
    dialog = SetupDialog(source, appearance, manage_service)
    if dialog.exec() != QDialog.Accepted:
        return 1
    choices = dialog.choices()
    return finish_setup(
        choices.source,
        choices.appearance,
        True,
        choices.install_service if manage_service else None,
    )


def finish_setup(
    source: Path | None,
    appearance: Appearance,
    update_appearance: bool,
    service_choice: bool | None,
) -> int:
    """Write setup choices without overwriting existing prompts.

    Parameters
    ----------
    source : pathlib.Path or None
        Existing root deck file to copy when available.
    appearance : Appearance
        Validated colors to write to ``config.toml``.
    update_appearance : bool
        Replace appearance values in an existing config when ``True``.
    service_choice : bool or None
        Install, remove, or leave the Linux user service unchanged.

    Returns
    -------
    int
        Zero on success or a nonzero validation or service error code.
    """
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    decks = directory / "decks.toml"
    if source and source.is_file():
        copy_without_overwrite(source, decks)
        copy_tree_without_overwrite(source.parent / "decks", directory / "decks")
    elif not decks.exists():
        decks.write_text(SAMPLE_DECKS, encoding="utf-8")

    for key in APPEARANCE_COLOR_KEYS:
        if not valid_color(getattr(appearance, key)):
            print(
                f"PromptDeck: {key} must be 'system' or #RRGGBB",
                file=sys.stderr,
            )
            return 2
    settings = directory / "config.toml"
    if not settings.exists() or update_appearance:
        settings.write_text(
            'version = 1\ndeck_source = "decks.toml"\n\n'
            + appearance_toml(appearance),
            encoding="utf-8",
        )
    install_desktop_entry()
    if service_choice is True:
        result = service("install")
        if result:
            return result
        result = service("restart")
        if result:
            return result
    elif service_choice is False and service_path().exists():
        result = service("uninstall")
        if result:
            return result
    print(f"PromptDeck config: {settings}")
    print_shortcut_help()
    return 0


def detect_legacy() -> Path | None:
    """Find the first supported legacy deck file."""
    candidates = (
        Path.home() / "PromptDeck" / "decks.toml",
        Path.home() / ".config" / "prompt-deck" / "decks.toml",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def copy_without_overwrite(source: str | Path, target: str | Path) -> str:
    """Copy one file unless the destination already exists."""
    source, target = Path(source), Path(target)
    if not target.exists():
        shutil.copy2(source, target)
    return str(target)


def copy_tree_without_overwrite(source: Path, target: Path) -> None:
    """Copy a deck directory while preserving every existing file."""
    if source.is_dir():
        shutil.copytree(
            source,
            target,
            dirs_exist_ok=True,
            copy_function=copy_without_overwrite,
        )


def executable() -> Path:
    """Return the absolute path to the installed PromptDeck command."""
    found = shutil.which("promptdeck")
    return Path(found or sys.argv[0]).expanduser().resolve()


def service_path() -> Path:
    """Return the systemd user-unit path."""
    config_home = Path(
        os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
    )
    return config_home / "systemd" / "user" / "promptdeck.service"


def service(action: str) -> int:
    """Install or control the Linux systemd user service."""
    if not sys.platform.startswith("linux"):
        print("PromptDeck user-service management is available on Linux only.", file=sys.stderr)
        return 2
    path = service_path()
    if action == "install":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(service_unit(executable()), encoding="utf-8")
        result = run_systemctl("daemon-reload")
        return result or run_systemctl("enable", "promptdeck.service")
    if action == "uninstall":
        run_systemctl("disable", "--now", "promptdeck.service")
        path.unlink(missing_ok=True)
        return run_systemctl("daemon-reload")
    systemd_action = "is-active" if action == "status" else action
    return run_systemctl(systemd_action, "promptdeck.service")


def run_systemctl(*args: str) -> int:
    """Run one systemctl user command and return its exit code."""
    return subprocess.run(["systemctl", "--user", *args], check=False).returncode


def service_unit(command: Path) -> str:
    """Render a user service for an installed PromptDeck command."""
    return (
        "[Unit]\nDescription=PromptDeck warm launcher\nAfter=graphical-session.target\nPartOf=graphical-session.target\n\n"
        f"[Service]\nType=simple\nExecStart={command} daemon\nRestart=on-failure\nRestartSec=3\n\n"
        "[Install]\nWantedBy=graphical-session.target\n"
    )


def install_desktop_entry() -> None:
    """Install the Linux desktop entry used by launchers and portals."""
    if not sys.platform.startswith("linux"):
        return
    data_home = Path(
        os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
    )
    path = data_home / "applications" / "promptdeck.desktop"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[Desktop Entry]\nType=Application\nName=PromptDeck\nComment=Open the prompt picker\n"
        f"Exec={executable()}\nTerminal=false\nCategories=Utility;\n",
        encoding="utf-8",
    )


def print_shortcut_help() -> None:
    """Print the command users can bind in their desktop settings."""
    command = executable()
    print(f"Shortcut command: {command}")
    if sys.platform.startswith("linux"):
        print("KDE: System Settings > Keyboard > Shortcuts > Add Command")
        print(f"Hyprland: bind = SUPER, P, exec, {command}")
    elif sys.platform == "win32":
        print("Windows: create a shortcut whose target is promptdeck.cmd")
