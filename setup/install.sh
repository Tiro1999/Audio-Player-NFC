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
# 2b. Unblock Bluetooth (rfkill) and ensure it stays unblocked
# ------------------------------------------------------------------
echo -e "\n>>> Unblocking Bluetooth …"
sudo rfkill unblock bluetooth
# Prevent bluetooth from being soft-blocked on future boots
if ! grep -q "rfkill unblock bluetooth" /etc/rc.local 2>/dev/null; then
    if [ -f /etc/rc.local ]; then
        sudo sed -i '/^exit 0/i rfkill unblock bluetooth' /etc/rc.local
    else
        sudo tee /etc/rc.local > /dev/null <<'RCEOF'
#!/bin/sh -e
rfkill unblock bluetooth
exit 0
RCEOF
        sudo chmod +x /etc/rc.local
    fi
fi
echo "Bluetooth unblocked (persisted in /etc/rc.local)"

# ------------------------------------------------------------------
# 2c. Note: /boot/firmware is FAT32 – chown/chmod are not supported.
# Tools use 'sudo cp' fallback to write config.json on this partition.
# ------------------------------------------------------------------

# ------------------------------------------------------------------
# 3. Create log directory + clean up stale log from old installs
# ------------------------------------------------------------------
echo -e "\n>>> Creating log directory …"
mkdir -p "$PROJECT_DIR/logs"
echo "Log directory: $PROJECT_DIR/logs/ (daily rotation, 3 days kept)"
# Remove old /var/log location if left over from a previous install
[ -f /var/log/nfc_player.log ] && sudo rm -f /var/log/nfc_player.log && echo "  Removed stale /var/log/nfc_player.log"

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

# Raspotify needs to share PulseAudio with our user.
# We use TCP (127.0.0.1:4713) because the Unix socket is unreliable
# for system services – PulseAudio may exit while idle, leaving a stale socket.
sudo mkdir -p /etc/systemd/system/raspotify.service.d
sudo tee /etc/systemd/system/raspotify.service.d/override.conf > /dev/null <<EOF
[Service]
User=$CURRENT_USER
Environment=XDG_RUNTIME_DIR=/run/user/$(id -u)
Environment=PULSE_SERVER=tcp:127.0.0.1
EOF

echo "Raspotify override:"
sudo cat /etc/systemd/system/raspotify.service.d/override.conf

# ------------------------------------------------------------------
# 6. PulseAudio for headless Bluetooth audio
# ------------------------------------------------------------------
echo -e "\n>>> Configuring PulseAudio …"
sudo loginctl enable-linger "$CURRENT_USER"
sudo usermod -a -G bluetooth "$CURRENT_USER"

mkdir -p "$USER_HOME/.config/pulse"

# Prevent PulseAudio from auto-exiting when idle (critical for Raspotify!)
cat > "$USER_HOME/.config/pulse/daemon.conf" <<'EOF'
# Managed by NFC-Player install script
exit-idle-time = -1
flat-volumes = no
EOF

# Enable bluetooth modules + TCP listener for Raspotify (system service)
cat > "$USER_HOME/.config/pulse/default.pa" <<'EOF'
.include /etc/pulse/default.pa
load-module module-bluetooth-discover
load-module module-bluetooth-policy
load-module module-switch-on-connect
# TCP listener on localhost for Raspotify (system service can't use Unix socket reliably)
load-module module-native-protocol-tcp auth-ip-acl=127.0.0.1 auth-anonymous=1
EOF

# Enable PulseAudio socket activation + service (for headless operation)
systemctl --user enable pulseaudio.socket pulseaudio.service || true
systemctl --user restart pulseaudio.socket || true
systemctl --user restart pulseaudio.service || true
# Give PA a moment to fully start and open TCP port
sleep 3

# Verify PulseAudio is running and TCP listener works
if pactl info &>/dev/null; then
    echo "PulseAudio running ✅"
    echo "  Default sink: $(pactl get-default-sink 2>/dev/null || echo 'unknown')"
else
    echo "⚠️  PulseAudio not responding – check 'systemctl --user status pulseaudio'"
fi

# ------------------------------------------------------------------
# 7. Install systemd services
# ------------------------------------------------------------------
echo -e "\n>>> Installing systemd services …"

# Patch service files with actual paths, user, and UID
CURRENT_UID="$(id -u)"
sed "s|__PROJECT_DIR__|$PROJECT_DIR|g; s|__USER__|$CURRENT_USER|g" \
    "$SCRIPT_DIR/nfc-player.service" | sudo tee /etc/systemd/system/nfc-player.service > /dev/null

sed "s|__PROJECT_DIR__|$PROJECT_DIR|g; s|__USER__|$CURRENT_USER|g; s|__UID__|$CURRENT_UID|g" \
    "$SCRIPT_DIR/bt-autoconnect.service" | sudo tee /etc/systemd/system/bt-autoconnect.service > /dev/null

sudo systemctl daemon-reload
sudo systemctl enable bt-autoconnect.service
sudo systemctl enable nfc-player.service

# ------------------------------------------------------------------
# 8. Shell aliases & login status banner
# ------------------------------------------------------------------
echo -e "\n>>> Setting up shell aliases & login banner …"

BASHRC="$USER_HOME/.bashrc"
MARKER="# --- NFC Spotify Player ---"

# Remove any previous NFC Player block, then append fresh
if grep -q "$MARKER" "$BASHRC" 2>/dev/null; then
    sed -i "/$MARKER/,/# --- END NFC Spotify Player ---/d" "$BASHRC"
fi

cat >> "$BASHRC" <<'BASHEOF'
# --- NFC Spotify Player ---
alias nfc-log='tail -f ~/nfc-player/logs/nfc_player.log &'
alias nfc-restart='sudo systemctl restart nfc-player bt-autoconnect && echo "✅ Services restarted"'
alias nfc-status='systemctl status nfc-player bt-autoconnect raspotify --no-pager -l'
alias nfc-test='python3 ~/nfc-player/tools/nfc_test.py'
alias nfc-bt='python3 ~/nfc-player/tools/bt_tools.py'
alias nfc-wifi='python3 ~/nfc-player/tools/wifi_tools.py'

# Login banner (only for interactive shells)
if [ -t 0 ] && [ -z "${_NFC_BANNER_SHOWN:-}" ]; then
    export _NFC_BANNER_SHOWN=1
    echo ""
    echo "🎵  NFC Spotify Player"
    echo "──────────────────────────────────"
    systemctl is-active --quiet nfc-player     && echo "  NFC Player:     ✅ running" || echo "  NFC Player:     ❌ stopped"
    systemctl is-active --quiet bt-autoconnect && echo "  BT AutoConnect: ✅ running" || echo "  BT AutoConnect: ❌ stopped"
    systemctl is-active --quiet raspotify      && echo "  Raspotify:      ✅ running" || echo "  Raspotify:      ❌ stopped"
    echo ""
    echo "  📋  Letzte Log-Einträge:"
    tail -5 ~/nfc-player/logs/nfc_player.log 2>/dev/null | sed 's/^/    /' || echo "    (noch kein Log)"
    echo ""
    echo "  Befehle: nfc-log · nfc-status · nfc-restart · nfc-test · nfc-bt · nfc-wifi"
    echo "──────────────────────────────────"
    echo ""
fi
# --- END NFC Spotify Player ---
BASHEOF

echo "Login banner & aliases added to $BASHRC"

# ------------------------------------------------------------------
# 9. Start services now
# ------------------------------------------------------------------
echo -e "\n>>> Starting services …"

# Ensure PulseAudio is alive before starting audio services
systemctl --user restart pulseaudio.service || true
sleep 2

# Verify PulseAudio TCP listener is active
if pactl info &>/dev/null; then
    echo "  PulseAudio:     ✅ running"
else
    echo "  PulseAudio:     ❌ NOT responding – audio will not work!"
fi

# 1. BT first – needs time to connect speaker + set PulseAudio sink
sudo systemctl restart bt-autoconnect.service
echo "  ⏳ Waiting for Bluetooth connection …"
sleep 8

# 2. Raspotify – needs PulseAudio + BT sink available
sudo systemctl restart raspotify.service
sleep 5

# Check if Raspotify survived startup (didn't crash)
if systemctl is-active --quiet raspotify; then
    echo "  Raspotify:      ✅ running"
else
    echo "  Raspotify:      ❌ CRASHED – checking logs:"
    journalctl -u raspotify --no-pager -n 5 | sed 's/^/    /'
fi

# 3. NFC Player last – needs Raspotify device to be visible
sudo systemctl restart nfc-player.service

echo -e "\n>>> Service status:"
systemctl is-active --quiet bt-autoconnect && echo "  BT AutoConnect: ✅ running" || echo "  BT AutoConnect: ❌ stopped"
systemctl is-active --quiet raspotify      && echo "  Raspotify:      ✅ running" || echo "  Raspotify:      ❌ stopped"
systemctl is-active --quiet nfc-player     && echo "  NFC Player:     ✅ running" || echo "  NFC Player:     ❌ stopped"

# ------------------------------------------------------------------
# 10. Done
# ------------------------------------------------------------------
echo ""
echo "========================================"
echo "  ✅  Installation complete!"
echo "========================================"
echo ""
echo "Voraussetzungen (einmalig):"
echo "  1. /boot/firmware/config.json existiert (siehe config.json.example)"
echo "  2. Spotify Token vorhanden (tools/spotify_auth.py auf dem PC ausführen)"
echo "  3. Bluetooth Speaker gepairt:  python3 ~/nfc-player/tools/bt_tools.py connect <MAC>"
echo ""
echo "Services laufen bereits! Bei nächstem Reboot starten sie automatisch."
echo ""
echo "Nützliche Befehle (neue SSH-Session oder 'source ~/.bashrc'):"
echo "  nfc-log      – Live Log-Ausgabe"
echo "  nfc-status   – Service-Status anzeigen"
echo "  nfc-restart  – Services neu starten"
echo "  nfc-test     – Spotify URI Test (ohne NFC Tag)"
echo "  nfc-bt       – Bluetooth Tools"
echo "  nfc-wifi     – WiFi Tools (add/list/remove/apply/scan)"
echo ""

# Try to activate aliases in current shell (won't work in subshell, but
# covers interactive use cases)
source "$BASHRC" 2>/dev/null || true
