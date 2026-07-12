import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .app import QApplication, PromptDeck, request_existing_daemon
from .config import DeckConfigError, config_dir, config_path, load_app_config, valid_accent


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
    result = argparse.ArgumentParser(prog="promptdeck", description="Open a keyboard-first prompt picker.")
    result.add_argument("--config", type=Path, help="config.toml or a deck TOML file")
    commands = result.add_subparsers(dest="command")
    commands.add_parser("daemon", help="run the warm foreground daemon")
    setup = commands.add_parser("setup", help="create config and optional Linux integration")
    setup.add_argument("--yes", action="store_true", help="accept safe defaults without prompting")
    setup.add_argument("--no-service", action="store_true", help="do not install the Linux user service")
    setup.add_argument("--accent", default=None, help="system or #RRGGBB")
    setup.add_argument("--migrate", type=Path, help="copy an existing decks.toml and sibling decks directory")
    service = commands.add_parser("service", help="manage the Linux user service")
    service.add_argument("action", choices=("install", "start", "stop", "restart", "status", "uninstall"))
    return result


def main(argv: list[str] | None = None) -> int:
    args, qt_args = parser().parse_known_args(argv)
    if args.command == "setup":
        return setup(args)
    if args.command == "service":
        return service(args.action)

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
    app.setDesktopFileName("io.github.paladin-tier-2.promptdeck")
    daemon = args.command == "daemon"
    app.setQuitOnLastWindowClosed(not daemon)
    widget = PromptDeck(config, daemon=daemon)
    if daemon:
        widget.start_server()
    else:
        widget.show_deck()
    return app.exec()


def setup(args: argparse.Namespace) -> int:
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    source = args.migrate.expanduser().resolve() if args.migrate else detect_legacy()
    if source and not args.yes:
        answer = input(f"Copy prompts from {source}? [Y/n] ").strip().lower()
        if answer not in ("", "y", "yes"):
            source = None
    decks = directory / "decks.toml"
    if source and source.is_file():
        copy_without_overwrite(source, decks)
        copy_tree_without_overwrite(source.parent / "decks", directory / "decks")
    elif not decks.exists():
        decks.write_text(SAMPLE_DECKS, encoding="utf-8")

    accent = args.accent
    if accent is None and not args.yes:
        accent = input("Accent color [system or #RRGGBB] (system): ").strip() or "system"
    accent = accent or "system"
    if not valid_accent(accent):
        print("PromptDeck: accent must be 'system' or #RRGGBB", file=sys.stderr)
        return 2
    settings = directory / "config.toml"
    if not settings.exists() or args.accent is not None:
        settings.write_text(
            f'version = 1\ndeck_source = "decks.toml"\n\n[appearance]\ntheme = "system"\naccent = "{accent}"\n',
            encoding="utf-8",
        )
    install_desktop_entry()
    if sys.platform.startswith("linux") and not args.no_service:
        service("install")
        service("restart")
    print(f"PromptDeck config: {settings}")
    print_shortcut_help()
    return 0


def detect_legacy() -> Path | None:
    for candidate in (Path.home() / "PromptDeck" / "decks.toml", Path.home() / ".config" / "prompt-deck" / "decks.toml"):
        if candidate.is_file():
            return candidate
    return None


def copy_without_overwrite(source: str | Path, target: str | Path) -> str:
    source, target = Path(source), Path(target)
    if not target.exists():
        shutil.copy2(source, target)
    return str(target)


def copy_tree_without_overwrite(source: Path, target: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=True, copy_function=copy_without_overwrite)


def executable() -> Path:
    found = shutil.which("promptdeck")
    return Path(found or sys.argv[0]).expanduser().resolve()


def service_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "systemd" / "user" / "promptdeck.service"


def service(action: str) -> int:
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
    return subprocess.run(["systemctl", "--user", *args], check=False).returncode


def service_unit(command: Path) -> str:
    return (
        "[Unit]\nDescription=PromptDeck warm launcher\nAfter=graphical-session.target\nPartOf=graphical-session.target\n\n"
        f"[Service]\nType=simple\nExecStart={command} daemon\nRestart=on-failure\nRestartSec=3\n\n"
        "[Install]\nWantedBy=graphical-session.target\n"
    )


def install_desktop_entry() -> None:
    if not sys.platform.startswith("linux"):
        return
    path = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "applications" / "promptdeck.desktop"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[Desktop Entry]\nType=Application\nName=PromptDeck\nComment=Open the prompt picker\n"
        f"Exec={executable()}\nTerminal=false\nCategories=Utility;\n",
        encoding="utf-8",
    )


def print_shortcut_help() -> None:
    print("Shortcut command: promptdeck")
    if sys.platform.startswith("linux"):
        print("KDE: System Settings > Keyboard > Shortcuts > Add Command")
        print('Hyprland: bind = SUPER, P, exec, promptdeck')
    elif sys.platform == "win32":
        print("Windows: create a shortcut whose target is promptdeck.cmd")
