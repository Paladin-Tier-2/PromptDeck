#!/bin/sh
set -eu

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
BIN_HOME="${XDG_BIN_HOME:-$HOME/.local/bin}"
VENV="$DATA_HOME/promptdeck/venv"

python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade promptdeck-qt
mkdir -p "$BIN_HOME"
ln -sf "$VENV/bin/promptdeck" "$BIN_HOME/promptdeck"
"$BIN_HOME/promptdeck" setup "$@"
