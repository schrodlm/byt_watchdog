#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"
CRON_HOURS="${1:-3}"

echo "=== Byt Watchdog - Install ==="

# Create venv if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# Install Python dependencies into venv
echo "Installing Python dependencies..."
"$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"

# Create data directory
mkdir -p "$SCRIPT_DIR/data"

# Check config
if [ ! -f "$SCRIPT_DIR/config.yaml" ]; then
    cp "$SCRIPT_DIR/config.example.yaml" "$SCRIPT_DIR/config.yaml"
    echo ""
    echo "Created config.yaml from template."
    echo ">>> EDIT config.yaml with your email settings before running! <<<"
    echo ""
fi

# Setup cron (all absolute paths so it works from any cwd)
PYTHON="$VENV_DIR/bin/python"
MAIN="$SCRIPT_DIR/main.py"
LOG="$SCRIPT_DIR/data/cron.log"
CRON_CMD="0 */${CRON_HOURS} * * * ${PYTHON} ${MAIN} >> ${LOG} 2>&1"

# Remove any existing entries for this project, then add new one
EXISTING=$(crontab -l 2>/dev/null | grep -v "$MAIN" || true)
printf '%s\n%s\n' "$EXISTING" "$CRON_CMD" | sed '/^$/d' | crontab -

echo ""
echo "Cron job installed: every ${CRON_HOURS} hours"
crontab -l | grep "$MAIN"
echo ""
echo "To test manually: ${PYTHON} ${MAIN} --dry-run"
echo "To view logs:     tail -f ${LOG}"
echo "To remove cron:   crontab -l | grep -v '$MAIN' | crontab -"
