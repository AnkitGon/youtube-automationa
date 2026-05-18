#!/bin/bash
# YouTube AI Agent — Linux/Raspberry Pi installer
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "=== YouTube AI Agent — Setup ==="
echo ""

# python check
if ! command -v python3 &>/dev/null; then
    echo "[!] python3 not found. Install with: sudo apt install python3 python3-pip"
    exit 1
fi

PYTHON=python3
if command -v python &>/dev/null && python --version 2>&1 | grep -q "Python 3"; then
    PYTHON=python
fi

# ffmpeg check
if ! command -v ffmpeg &>/dev/null; then
    echo "[!] ffmpeg not found. Installing..."
    sudo apt-get install -y ffmpeg
fi

# venv
if [ ! -d "venv" ]; then
    echo "[*] Creating virtual environment..."
    $PYTHON -m venv venv
fi

source venv/bin/activate

echo "[*] Installing dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo ""
echo "[✓] Installation complete."
echo ""

# alias
SHELL_RC="$HOME/.bashrc"
[ -n "$ZSH_VERSION" ] && SHELL_RC="$HOME/.zshrc"

ALIAS_LINE="alias agent='cd \"$SCRIPT_DIR\" && source venv/bin/activate && python agent.py'"
if ! grep -q "alias agent=" "$SHELL_RC" 2>/dev/null; then
    echo "$ALIAS_LINE" >> "$SHELL_RC"
    echo "[✓] Added 'agent' alias to $SHELL_RC"
    echo "    Run: source $SHELL_RC"
fi

echo "[*] Starting wizard..."
echo ""
python wizard.py
