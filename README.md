# PromptDeck

PromptDeck is a small keyboard-first prompt picker. It opens over the current screen, copies a saved prompt, and gets out of the way. Its colors follow the desktop's Qt palette by default and can be changed in setup or `config.toml`.

## Install

PromptDeck requires Python 3.10 or newer.

```bash
pip install promptdeck-qt
promptdeck setup
```

Setup has separate prompt and appearance pages. The appearance page shows the real overlay and updates it while you choose colors. Use `promptdeck setup --terminal` if you prefer terminal prompts, or `--yes` for unattended setup.

The isolated Linux installer keeps the application out of your project folders:

```bash
curl -fsSL https://raw.githubusercontent.com/Paladin-Tier-2/PromptDeck/main/install.sh | sh
```

On Windows, download and run the installer:

```powershell
Invoke-WebRequest https://raw.githubusercontent.com/Paladin-Tier-2/PromptDeck/main/install.ps1 -OutFile install.ps1
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

Re-running either installer upgrades the package without overwriting your configuration or prompts. Windows autostart is intentionally not installed in v0.1.

## Use

```bash
promptdeck
promptdeck daemon
promptdeck service start
promptdeck service stop
promptdeck service restart
promptdeck service status
```

On Linux, `promptdeck setup` installs and starts `promptdeck.service`, a systemd **user** service. Plain `promptdeck` asks that warm daemon to show the overlay. If the daemon is stopped, it opens a one-shot process instead.

Controls: `Tab` changes deck; arrows or `H/J/K/L` move; `1`-`9` and `0` select directly; `Enter` or `Space` copies; `Esc` or `Backspace` closes.

## Configuration

Setup stores private files outside the repository:

- Linux: `${XDG_CONFIG_HOME:-~/.config}/promptdeck`
- Windows: `%APPDATA%\PromptDeck`

`config.toml`:

```toml
version = 1
deck_source = "decks.toml"

[appearance]
accent = "system" # or "#7c3aed"
card_background = "system"
card_border = "system"
selected_border = "system"
card_text = "system"
```

Each deck has a name and cards:

```toml
[[decks]]
name = "Writing"

[[decks.cards]]
title = "Make concise"
key = "C"
body = "Make this shorter without changing its meaning."
```

Split larger collections with `include = ["decks/*.toml"]`. PromptDeck reloads the config, included decks, and colors whenever the overlay opens.

Config precedence is `--config`, then `PROMPTDECK_CONFIG`, then the native default. `--config` may point to either `config.toml` or a deck file.

Setup safely detects the old `~/PromptDeck/decks.toml` and `~/.config/prompt-deck/decks.toml` locations. Migration copies the root file and sibling `decks/` directory; it never moves, deletes, or overwrites files. For unattended setup:

```bash
promptdeck setup --yes --accent system
promptdeck setup --yes --migrate /path/to/decks.toml
promptdeck setup --yes --no-service
```

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python -m build
```

The GitHub Actions test matrix covers Linux and Windows and verifies a clean wheel install.
