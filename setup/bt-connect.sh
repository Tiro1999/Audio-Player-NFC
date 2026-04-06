#!/usr/bin/env bash
# bt-connect.sh – Continuously ensure the Bluetooth speaker stays connected.
#
# Installed to /usr/local/bin/bt-connect.sh by setup/install.sh.
# Managed by bt-connect.service (systemd).
#
# The MAC address is read from /boot/config.json at startup so that it can
# be changed just by editing the config file on the boot partition.

set -euo pipefail

CONFIG_FILE="/boot/config.json"
INTERVAL=10  # seconds between connection checks

# Read MAC address from config.json
if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "[bt-connect] Config file $CONFIG_FILE not found – exiting." >&2
    exit 1
fi

BT_MAC=$(python3 -c "import json; c=json.load(open('$CONFIG_FILE')); print(c['bluetooth']['mac_address'])" 2>/dev/null)
BT_NAME=$(python3 -c "import json; c=json.load(open('$CONFIG_FILE')); print(c['bluetooth'].get('device_name','Speaker'))" 2>/dev/null || echo "Speaker")

if [[ -z "$BT_MAC" ]]; then
    echo "[bt-connect] No bluetooth.mac_address in config – exiting." >&2
    exit 1
fi

echo "[bt-connect] Monitoring connection to '$BT_NAME' ($BT_MAC), interval=${INTERVAL}s"

# Ensure Bluetooth adapter is powered on
bluetoothctl -- power on >/dev/null 2>&1 || true

while true; do
    if bluetoothctl -- info "$BT_MAC" 2>/dev/null | grep -q "Connected: yes"; then
        : # Already connected – nothing to do
    else
        echo "[bt-connect] Not connected. Attempting to connect to $BT_NAME ($BT_MAC)…"
        bluetoothctl -- connect "$BT_MAC" >/dev/null 2>&1 && \
            echo "[bt-connect] Connected to $BT_NAME ($BT_MAC)." || \
            echo "[bt-connect] Connection attempt failed – will retry in ${INTERVAL}s."
    fi
    sleep "$INTERVAL"
done
