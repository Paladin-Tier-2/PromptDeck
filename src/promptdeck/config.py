"""Load PromptDeck settings and deck files from native config paths."""

import glob
import os
import re
import sys
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib
from dataclasses import dataclass
from pathlib import Path


class DeckConfigError(ValueError):
    """Raised when a settings or deck file is missing or invalid."""

    pass


@dataclass(frozen=True)
class Card:
    """One selectable prompt card."""

    title: str
    body: str
    key: str = ""


@dataclass(frozen=True)
class Deck:
    """A named collection of prompt cards."""

    name: str
    cards: list[Card]


@dataclass(frozen=True)
class Appearance:
    """Colors used to draw the overlay.

    Attributes
    ----------
    selected_background : str
        Selected card fill, or ``system``.
    card_background : str
        Unselected card fill, or ``system``.
    card_border : str
        Unselected card outline, or ``system``.
    selected_border : str
        Selected card outline, or ``system``.
    card_text : str
        Unselected card text, or ``system``.
    """

    selected_background: str = "system"
    card_background: str = "system"
    card_border: str = "system"
    selected_border: str = "system"
    card_text: str = "system"


APPEARANCE_COLOR_KEYS = (
    "selected_background",
    "selected_border",
    "card_background",
    "card_border",
    "card_text",
)


@dataclass(frozen=True)
class AppConfig:
    """Resolved settings, source paths, appearance, and decks."""

    path: Path
    deck_source: Path
    appearance: Appearance
    decks: list[Deck]


def config_dir() -> Path:
    """Return the native per-user PromptDeck config directory."""
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "PromptDeck"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "promptdeck"


def config_path(explicit: Path | None = None) -> Path:
    """Resolve config precedence: argument, environment, then native default."""
    if explicit is not None:
        return explicit.expanduser().resolve()
    configured = os.environ.get("PROMPTDECK_CONFIG")
    return Path(configured).expanduser().resolve() if configured else config_dir() / "config.toml"


def load_app_config(path: Path) -> AppConfig:
    """Load app settings and the deck source they reference."""
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
    if theme != "system":
        raise DeckConfigError("appearance.theme currently supports only 'system'")
    colors = {key: appearance_data.get(key, "system") for key in APPEARANCE_COLOR_KEYS}
    if "selected_background" not in appearance_data:
        colors["selected_background"] = appearance_data.get("accent", "system")
    for key, value in colors.items():
        if not valid_color(value):
            raise DeckConfigError(
                f"appearance.{key} must be 'system' or #RRGGBB"
            )
    source = (path.parent / source_name).resolve()
    return AppConfig(
        path,
        source,
        Appearance(**colors),
        load_decks(source),
    )


def valid_color(value: object) -> bool:
    """Check one appearance color.

    Parameters
    ----------
    value : object
        Value read from configuration or setup.

    Returns
    -------
    bool
        ``True`` for ``system`` or a six-digit hex color.
    """
    return isinstance(value, str) and (
        value == "system" or re.fullmatch(r"#[0-9a-fA-F]{6}", value) is not None
    )


def valid_accent(value: object) -> bool:
    """Check an accent value for older integrations.

    Parameters
    ----------
    value : object
        Accent value to validate.

    Returns
    -------
    bool
        Result from :func:`valid_color`.
    """
    return valid_color(value)


def appearance_toml(appearance: Appearance) -> str:
    """Format the appearance table shown and written by setup.

    Parameters
    ----------
    appearance : Appearance
        Appearance values to serialize.

    Returns
    -------
    str
        Complete TOML ``appearance`` table with a trailing newline.
    """
    lines = ["[appearance]"]
    lines.extend(
        f'{key} = "{getattr(appearance, key)}"' for key in APPEARANCE_COLOR_KEYS
    )
    return "\n".join(lines) + "\n"


def load_decks(source: Path) -> list[Deck]:
    """Load and validate every deck reachable from *source*."""
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
