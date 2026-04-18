#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CRON_HOURS="${1:-3}"

echo "=== Byt Watchdog - Install ==="

# Install Python dependencies
echo "Installing Python dependencies..."
pip3 install --user -r "$SCRIPT_DIR/requirements.txt"

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

# Setup cron
CRON_CMD="0 */${CRON_HOURS} * * * cd ${SCRIPT_DIR} && $(which python3) main.py >> data/cron.log 2>&1"

# Remove any existing byt_watchdog cron entries, then add new one
(crontab -l 2>/dev/null | grep -v "byt_watchdog\|${SCRIPT_DIR}/main.py"; echo "$CRON_CMD") | crontab -

echo "Cron job installed: every ${CRON_HOURS} hours"
echo "  ${CRON_CMD}"
echo ""
echo "To test manually: cd ${SCRIPT_DIR} && python3 main.py"
echo "To view logs:     tail -f ${SCRIPT_DIR}/data/cron.log"
echo "To remove cron:   crontab -l | grep -v '${SCRIPT_DIR}/main.py' | crontab -"
