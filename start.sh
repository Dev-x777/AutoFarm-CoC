#!/bin/bash
# AutoFarm CoC - Smart Launcher
# Auto-activates the virtual environment and starts the bot.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON="$SCRIPT_DIR/.venv/bin/python3"

if [ ! -f "$PYTHON" ]; then
    echo "❌ Virtual environment not found."
    echo "   Run:  python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

echo "⚔️  AutoFarm CoC — Starting..."
echo ""
"$PYTHON" main.py "$@"
