/home/eko/.bashrc: line 104: bind: warning: line editing not enabled
import glob
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

    try:
        with path.open("rb") as source:
            data = tomllib.load(source)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise DeckConfigError(f"Could not read {path}: {exc}") from exc

    decks = _parse_decks(data.get("decks", []), path)
    for pattern in _include_patterns(data.get("include", []), path):
        for match in sorted(glob.glob(str(path.parent / pattern))):
            decks.extend(_load_recursive(Path(match), visited))
    return decks


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
