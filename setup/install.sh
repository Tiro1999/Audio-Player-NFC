#!/usr/bin/env bash
# install.sh – One-time setup script for the NFC Audio Player on Raspberry Pi OS Lite.
#
# Run as root:
#   sudo bash setup/install.sh
#
# What this script does:
#   1. Install system dependencies (BlueZ, Python3, SPI tools, Raspotify).
#   2. Enable the SPI interface (required for the RC522 NFC module).
#   3. Install Python packages from requirements.txt.
#   4. Configure WiFi networks from /boot/config.json.
#   5. Perform an initial Bluetooth pairing / trust for the configured speaker.
#   6. Complete the Spotify OAuth flow (opens the auth URL).
#   7. Install and enable systemd services for auto-start.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
SERVICE_USER="${SUDO_USER:-pi}"
HOME_DIR="$(eval echo "~${SERVICE_USER}")"
CONFIG_FILE="/boot/config.json"

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ── Sanity checks ─────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    error "This script must be run as root (sudo bash setup/install.sh)"
    exit 1
fi

if [[ ! -f "$CONFIG_FILE" ]]; then
    warn "Config file not found at $CONFIG_FILE"
    info "Copying config.example.json → $CONFIG_FILE"
    cp "$REPO_DIR/config.example.json" "$CONFIG_FILE"
    info "Please edit $CONFIG_FILE with your WiFi, Spotify and Bluetooth settings,"
    info "then re-run this script."
    exit 0
fi

# ── 1. System packages ────────────────────────────────────────────────────────
info "Updating package lists…"
apt-get update -qq

info "Installing system dependencies…"
apt-get install -y -qq \
    python3 python3-pip python3-venv \
    bluetooth bluez bluez-tools \
    pulseaudio pulseaudio-module-bluetooth \
    curl wget git

# ── 2. Enable SPI ─────────────────────────────────────────────────────────────
info "Enabling SPI interface for RC522…"
if ! grep -qE "^dtparam=spi=on" /boot/config.txt 2>/dev/null; then
    echo "dtparam=spi=on" >> /boot/config.txt
    info "SPI enabled in /boot/config.txt (takes effect after reboot)"
else
    info "SPI already enabled."
fi

# ── 3. Install Raspotify ──────────────────────────────────────────────────────
if ! systemctl is-active --quiet raspotify 2>/dev/null; then
    info "Installing Raspotify (Spotify Connect receiver)…"
    curl -sL https://dtcooper.github.io/raspotify/install.sh | bash || \
        warn "Raspotify install failed – install manually if needed."
else
    info "Raspotify already installed and running."
fi

# Update Raspotify device name from config
DEVICE_NAME=$(python3 -c "import json; c=json.load(open('$CONFIG_FILE')); print(c['spotify']['device_name'])" 2>/dev/null || echo "NFC-Player")
RASPOTIFY_CONF="/etc/raspotify/conf"
if [[ -f "$RASPOTIFY_CONF" ]]; then
    sed -i "s/^#\?DEVICE_NAME=.*/DEVICE_NAME=\"$DEVICE_NAME\"/" "$RASPOTIFY_CONF"
    info "Raspotify device name set to '$DEVICE_NAME'."
fi

# ── 4. Python virtual environment + packages ──────────────────────────────────
VENV_DIR="$HOME_DIR/nfc-player-venv"
info "Creating Python virtual environment at $VENV_DIR…"
python3 -m venv "$VENV_DIR"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "$VENV_DIR"

info "Installing Python packages…"
sudo -u "$SERVICE_USER" "$VENV_DIR/bin/pip" install --quiet --upgrade pip
sudo -u "$SERVICE_USER" "$VENV_DIR/bin/pip" install --quiet -r "$REPO_DIR/requirements.txt"

# ── 5. Configure WiFi (wpa_supplicant) ────────────────────────────────────────
info "Configuring WiFi networks…"
python3 - <<'PYEOF'
import json, pathlib, sys

config_path = "/boot/config.json"
wpa_path    = pathlib.Path("/etc/wpa_supplicant/wpa_supplicant.conf")

with open(config_path) as f:
    config = json.load(f)

networks = config.get("wifi", [])
if not networks:
    print("No WiFi networks in config – skipping.")
    sys.exit(0)

blocks = []
for net in sorted(networks, key=lambda n: -n.get("priority", 0)):
    ssid     = net["ssid"]
    password = net["password"]
    priority = net.get("priority", 1)
    blocks.append(
        f'network={{\n'
        f'    ssid="{ssid}"\n'
        f'    psk="{password}"\n'
        f'    priority={priority}\n'
        f'    key_mgmt=WPA-PSK\n'
        f'}}'
    )

header = (
    "ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev\n"
    "update_config=1\n"
    "country=DE\n\n"
)
wpa_path.write_text(header + "\n\n".join(blocks) + "\n")
print(f"Written {len(networks)} network(s) to {wpa_path}")
PYEOF
wpa_cli -i wlan0 reconfigure 2>/dev/null || true

# ── 6. Bluetooth pairing ──────────────────────────────────────────────────────
BT_MAC=$(python3 -c "import json; c=json.load(open('$CONFIG_FILE')); print(c['bluetooth']['mac_address'])" 2>/dev/null || true)
BT_NAME=$(python3 -c "import json; c=json.load(open('$CONFIG_FILE')); print(c['bluetooth'].get('device_name','Speaker'))" 2>/dev/null || true)

if [[ -n "$BT_MAC" && "$BT_MAC" != "AA:BB:CC:DD:EE:FF" ]]; then
    info "Pairing Bluetooth device '$BT_NAME' ($BT_MAC)…"
    bluetoothctl -- power on
    bluetoothctl -- agent on
    bluetoothctl -- default-agent

    info "Please make sure '$BT_NAME' is in pairing mode, then press Enter."
    read -r

    bluetoothctl -- pair   "$BT_MAC" || warn "Pairing may have already been done."
    bluetoothctl -- trust  "$BT_MAC"
    bluetoothctl -- connect "$BT_MAC" || warn "Could not connect now – will retry at boot."
    info "Bluetooth setup complete."
else
    warn "Bluetooth MAC address not set or is still placeholder – skipping pairing."
    warn "Update bluetooth.mac_address in $CONFIG_FILE and re-run."
fi

# ── 7. Spotify OAuth ──────────────────────────────────────────────────────────
info "Starting Spotify OAuth flow…"
info "A URL will be printed. Open it in a browser, authorise the app and paste"
info "the redirected URL back here."
sudo -u "$SERVICE_USER" "$VENV_DIR/bin/python3" - <<'PYEOF'
import json, sys
with open("/boot/config.json") as f:
    cfg = json.load(f)["spotify"]

import spotipy
from spotipy.oauth2 import SpotifyOAuth

auth = SpotifyOAuth(
    client_id=cfg["client_id"],
    client_secret=cfg["client_secret"],
    redirect_uri=cfg.get("redirect_uri", "http://localhost:8888/callback"),
    scope="user-read-playback-state user-modify-playback-state user-read-currently-playing",
    cache_path="/home/pi/.spotify_token_cache",
    open_browser=False,
)
url = auth.get_authorize_url()
print(f"\n\nOpen this URL in a browser:\n{url}\n")
redirected = input("Paste the full redirected URL here: ").strip()
code = auth.parse_response_code(redirected)
auth.get_access_token(code)
print("Spotify token saved successfully.")
PYEOF

# ── 8. Install systemd services ───────────────────────────────────────────────
info "Installing systemd services…"

# Substitute paths in the service templates
for svc in nfc-player.service bt-connect.service; do
    src="$SCRIPT_DIR/$svc"
    dst="/etc/systemd/system/$svc"
    sed \
        -e "s|%REPO_DIR%|$REPO_DIR|g" \
        -e "s|%VENV_DIR%|$VENV_DIR|g" \
        -e "s|%SERVICE_USER%|$SERVICE_USER|g" \
        "$src" > "$dst"
    info "Installed $dst"
done

# Install bt-connect.sh
cp "$SCRIPT_DIR/bt-connect.sh" /usr/local/bin/bt-connect.sh
chmod +x /usr/local/bin/bt-connect.sh

systemctl daemon-reload
systemctl enable raspotify
systemctl enable bt-connect.service
systemctl enable nfc-player.service

info ""
info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
info " Installation complete!"
info " Reboot the Raspberry Pi to start all services:"
info "   sudo reboot"
info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
