# PromptDeck

PromptDeck is a small keyboard-first prompt picker. It opens as a full-screen overlay, lets me choose a saved prompt, copies it to the clipboard, and gets out of the way.

I built it because I wanted my recurring prompts available from one global shortcut without searching through notes or keeping another application open.

The interface is built with Qt. On Linux it uses `wl-copy` for the Wayland clipboard and `notify-send` for the confirmation message. On Windows it uses the Qt clipboard directly.

## Setup

### Linux

```bash
git clone https://github.com/Paladin-Tier-2/PromptDeck.git ~/PromptDeck
cd ~/PromptDeck
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp examples/decks.toml decks.toml
python prompt_deck.py
```

On Fedora, install the two small desktop dependencies:

```bash
sudo dnf install wl-clipboard libnotify
```

### Windows

```powershell
git clone --branch windows-support https://github.com/Paladin-Tier-2/PromptDeck.git
cd PromptDeck
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item examples\decks.toml decks.toml
python prompt_deck.py
```

Your `decks.toml` file is ignored by Git. Prompt text often becomes personal, so the repository includes only a generic example.

## Deck format

Each deck has a name and a list of cards. Each card has a title, an optional letter shortcut, and the text to copy.

```toml
[[decks]]
name = "Writing"

[[decks.cards]]
title = "Make concise"
key = "C"
body = "Make this shorter without changing its meaning."
```

Larger collections can be split across files with recursive includes:

```toml
include = ["decks/*.toml"]
```

Patterns are resolved relative to the file that contains them. Files are loaded in sorted order, and already visited files are skipped to prevent include cycles.

## Controls

- `Tab`: next deck
- `Shift+Tab`: previous deck
- `1`-`9`, `0`: choose a card directly
- Arrow keys or `H/J/K/L`: move the selection
- `Enter` or `Space`: copy and close
- `Esc` or `Backspace`: close without copying

## Daemon mode

Running the app as a daemon keeps Qt warm, so a desktop shortcut can open it without the normal startup delay:

```bash
python prompt_deck.py --daemon
```

Show the running daemon with:

```bash
python prompt_deck.py --show
```

If no daemon is running, the same command starts PromptDeck normally.

## Platform support

The `main` branch is the Linux/Wayland version I use. This branch adds Windows support, but it still needs testing on a real Windows machine.
