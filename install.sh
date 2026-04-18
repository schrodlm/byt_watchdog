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

# Setup cron (uses venv python)
PYTHON="$VENV_DIR/bin/python"
CRON_CMD="0 */${CRON_HOURS} * * * cd ${SCRIPT_DIR} && ${PYTHON} main.py >> data/cron.log 2>&1"

# Remove any existing byt_watchdog cron entries, then add new one
(crontab -l 2>/dev/null | grep -v "byt_watchdog\|${SCRIPT_DIR}/main.py"; echo "$CRON_CMD") | crontab -

echo ""
echo "Cron job installed: every ${CRON_HOURS} hours"
echo "  ${CRON_CMD}"
echo ""
echo "To test manually: cd ${SCRIPT_DIR} && ${PYTHON} main.py"
echo "To view logs:     tail -f ${SCRIPT_DIR}/data/cron.log"
echo "To remove cron:   crontab -l | grep -v '${SCRIPT_DIR}/main.py' | crontab -"
