import glob
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path


class DeckConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Card:
    title: str
    body: str
    key: str = ""


@dataclass(frozen=True)
class Deck:
    name: str
    cards: list[Card]


@dataclass(frozen=True)
class Appearance:
    theme: str = "system"
    accent: str = "system"


@dataclass(frozen=True)
class AppConfig:
    path: Path
    deck_source: Path
    appearance: Appearance
    decks: list[Deck]


def config_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "PromptDeck"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "promptdeck"


def config_path(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    configured = os.environ.get("PROMPTDECK_CONFIG")
    return Path(configured).expanduser().resolve() if configured else config_dir() / "config.toml"


def load_app_config(path: Path) -> AppConfig:
    path = path.expanduser().resolve()
    data = _read_toml(path)
    # A direct deck file remains useful for --config and safe migration.
    if "decks" in data or "include" in data:
        return AppConfig(path, path, Appearance(), load_decks(path))

    version = data.get("version", 1)
    if version != 1:
        raise DeckConfigError(f"Unsupported config version {version} in {path}")
    source_name = data.get("deck_source", "decks.toml")
    if not isinstance(source_name, str) or not source_name.strip():
        raise DeckConfigError(f"'deck_source' must be non-empty text in {path}")
    appearance_data = data.get("appearance", {})
    if not isinstance(appearance_data, dict):
        raise DeckConfigError(f"'appearance' must be a table in {path}")
    theme = appearance_data.get("theme", "system")
    accent = appearance_data.get("accent", "system")
    if theme != "system":
        raise DeckConfigError("appearance.theme currently supports only 'system'")
    if not valid_accent(accent):
        raise DeckConfigError("appearance.accent must be 'system' or #RRGGBB")
    source = (path.parent / source_name).resolve()
    return AppConfig(path, source, Appearance(theme, accent), load_decks(source))


def valid_accent(value: object) -> bool:
    return isinstance(value, str) and (value == "system" or re.fullmatch(r"#[0-9a-fA-F]{6}", value) is not None)


def load_decks(source: Path) -> list[Deck]:
    source = source.expanduser().resolve()
    if not source.is_file():
        raise DeckConfigError(f"Configuration not found: {source}")

    decks = _load_recursive(source, visited=set())
    if not decks:
        raise DeckConfigError(f"No decks found in {source}")
    return decks


def _load_recursive(path: Path, visited: set[Path]) -> list[Deck]:
    path = path.resolve()
    if path in visited:
        return []
    visited.add(path)

    data = _read_toml(path)

    decks = _parse_decks(data.get("decks", []), path)
    for pattern in _include_patterns(data.get("include", []), path):
        for match in sorted(glob.glob(str(path.parent / pattern))):
            decks.extend(_load_recursive(Path(match), visited))
    return decks


def _read_toml(path: Path) -> dict:
    if not path.is_file():
        raise DeckConfigError(f"Configuration not found: {path}")
    try:
        with path.open("rb") as source:
            return tomllib.load(source)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise DeckConfigError(f"Could not read {path}: {exc}") from exc


def _parse_decks(raw_decks: object, path: Path) -> list[Deck]:
    if not isinstance(raw_decks, list):
        raise DeckConfigError(f"'decks' must be a list in {path}")

    decks = []
    for deck_index, raw_deck in enumerate(raw_decks, start=1):
        if not isinstance(raw_deck, dict):
            raise DeckConfigError(f"Deck {deck_index} must be a table in {path}")

        name = _required_text(raw_deck, "name", f"deck {deck_index}", path)
        raw_cards = raw_deck.get("cards", [])
        if not isinstance(raw_cards, list) or not raw_cards:
            raise DeckConfigError(f"Deck '{name}' needs at least one card in {path}")

        cards = []
        for card_index, raw_card in enumerate(raw_cards, start=1):
            if not isinstance(raw_card, dict):
                raise DeckConfigError(
                    f"Card {card_index} in deck '{name}' must be a table in {path}"
                )
            context = f"card {card_index} in deck '{name}'"
            title = _required_text(raw_card, "title", context, path)
            body = _required_text(raw_card, "body", context, path) + "\n"
            key = raw_card.get("key", "")
            if not isinstance(key, str):
                raise DeckConfigError(f"'key' must be text for {context} in {path}")
            cards.append(Card(title=title, body=body, key=key.strip()))

        decks.append(Deck(name=name, cards=cards))
    return decks


def _required_text(data: dict, field: str, context: str, path: Path) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        message = f"'{field}' must be non-empty text for {context} in {path}"
        raise DeckConfigError(message)
    return value.strip()


def _include_patterns(raw_patterns: object, path: Path) -> list[str]:
    if not isinstance(raw_patterns, list) or not all(
        isinstance(pattern, str) for pattern in raw_patterns
    ):
        raise DeckConfigError(f"'include' must be a list of paths in {path}")
    return raw_patterns
