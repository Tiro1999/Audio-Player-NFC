#!/usr/bin/env bash
# ===========================================================================
#  NFC Spotify Player – Installation Script
#  Run on the Raspberry Pi via SSH:   bash setup/install.sh
# ===========================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CURRENT_USER="$(whoami)"
USER_HOME="$HOME"

echo "========================================"
echo "  NFC Spotify Player – Installer"
echo "  User : $CURRENT_USER"
echo "  Home : $USER_HOME"
echo "========================================"

# ------------------------------------------------------------------
# 1. System packages
# ------------------------------------------------------------------
echo -e "\n>>> Updating system packages …"
sudo apt update && sudo apt upgrade -y

echo -e "\n>>> Installing dependencies …"
sudo apt install -y \
    python3-pip \
    python3-venv \
    python3-smbus \
    i2c-tools \
    bluez \
    pulseaudio \
    pulseaudio-module-bluetooth

# ------------------------------------------------------------------
# 2. Enable I2C interface
# ------------------------------------------------------------------
echo -e "\n>>> Enabling I2C …"
sudo raspi-config nonint do_i2c 0
echo "I2C enabled (reboot may be required for first use)"

# ------------------------------------------------------------------
# 3. Create log file
# ------------------------------------------------------------------
echo -e "\n>>> Creating log file …"
sudo touch /var/log/nfc_player.log
sudo chown "$CURRENT_USER":"$CURRENT_USER" /var/log/nfc_player.log
sudo chmod 644 /var/log/nfc_player.log
echo "Log file: /var/log/nfc_player.log"

# ------------------------------------------------------------------
# 4. Python virtual environment
# ------------------------------------------------------------------
VENV_DIR="$PROJECT_DIR/venv"
echo -e "\n>>> Setting up Python venv in $VENV_DIR …"
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install -r "$PROJECT_DIR/requirements.txt"

# ------------------------------------------------------------------
# 5. Install Raspotify (Spotify Connect receiver)
# ------------------------------------------------------------------
echo -e "\n>>> Installing Raspotify …"
if ! command -v raspotify &>/dev/null; then
    curl -sL https://dtcooper.github.io/raspotify/install.sh | sh
else
    echo "Raspotify already installed, skipping"
fi

# Read device name from config.json
DEVICE_NAME=$(python3 -c "
import json, os
for p in ['/boot/firmware/config.json', '/boot/config.json']:
    if os.path.exists(p):
        print(json.load(open(p)).get('spotify',{}).get('device_name','NFC-Box'))
        break
else:
    print('NFC-Box')
" 2>/dev/null)

echo "Raspotify device name: $DEVICE_NAME"
sudo tee /etc/raspotify/conf > /dev/null <<EOF
# Managed by NFC-Player install script
LIBRESPOT_NAME="$DEVICE_NAME"
LIBRESPOT_BACKEND="pulseaudio"
LIBRESPOT_BITRATE="160"
LIBRESPOT_QUIET=
EOF

# Raspotify needs to share PulseAudio with our user
sudo mkdir -p /etc/systemd/system/raspotify.service.d
sudo tee /etc/systemd/system/raspotify.service.d/override.conf > /dev/null <<EOF
[Service]
User=$CURRENT_USER
Environment=PULSE_RUNTIME_PATH=/run/user/$(id -u)/pulse
EOF

# ------------------------------------------------------------------
# 6. PulseAudio for headless Bluetooth audio
# ------------------------------------------------------------------
echo -e "\n>>> Configuring PulseAudio …"
sudo loginctl enable-linger "$CURRENT_USER"
sudo usermod -a -G bluetooth "$CURRENT_USER"

mkdir -p "$USER_HOME/.config/pulse"
# Enable bluetooth module auto-loading
if ! grep -q "module-bluetooth-discover" "$USER_HOME/.config/pulse/default.pa" 2>/dev/null; then
    cat >> "$USER_HOME/.config/pulse/default.pa" <<'EOF'
.include /etc/pulse/default.pa
load-module module-bluetooth-discover
load-module module-bluetooth-policy
EOF
fi

# Start PulseAudio user service
systemctl --user enable pulseaudio || true
systemctl --user start pulseaudio || true

# ------------------------------------------------------------------
# 7. Install systemd services
# ------------------------------------------------------------------
echo -e "\n>>> Installing systemd services …"

# Patch service files with actual paths
sed "s|__PROJECT_DIR__|$PROJECT_DIR|g; s|__USER__|$CURRENT_USER|g" \
    "$SCRIPT_DIR/nfc-player.service" | sudo tee /etc/systemd/system/nfc-player.service > /dev/null

sed "s|__PROJECT_DIR__|$PROJECT_DIR|g; s|__USER__|$CURRENT_USER|g" \
    "$SCRIPT_DIR/bt-autoconnect.service" | sudo tee /etc/systemd/system/bt-autoconnect.service > /dev/null

sudo systemctl daemon-reload
sudo systemctl enable bt-autoconnect.service
sudo systemctl enable nfc-player.service

# ------------------------------------------------------------------
# 8. Reminder: config & token
# ------------------------------------------------------------------
echo ""
echo "========================================"
echo "  ✅  Installation complete!"
echo "========================================"
echo ""
echo "Before starting, make sure:"
echo "  1. /boot/firmware/config.json exists (see config.json.example)"
echo "  2. /boot/firmware/spotify_cache exists (run tools/spotify_auth.py on PC)"
echo "  3. Bluetooth speaker is paired:  bluetoothctl pair <MAC>"
echo ""
echo "Then start services:"
echo "  sudo systemctl start bt-autoconnect"
echo "  sudo systemctl start nfc-player"
echo ""
echo "Or reboot:  sudo reboot"
