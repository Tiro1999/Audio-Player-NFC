#!/usr/bin/env bash
# ===========================================================================
#  deploy.sh – Copy all project files to the Raspberry Pi
#  Reads PI_IP and PI_USER from .env
# ===========================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Load .env
if [ ! -f .env ]; then
    echo "❌  .env not found. Copy .env.example → .env and fill in your values."
    exit 1
fi
source .env

# Strip Windows \r from sourced values
PI_IP="$(echo "$PI_IP" | tr -d '\r')"
PI_USER="$(echo "$PI_USER" | tr -d '\r')"

: "${PI_IP:?PI_IP not set in .env}"
: "${PI_USER:?PI_USER not set in .env}"

TARGET="$PI_USER@$PI_IP"
REMOTE_DIR="~/nfc-player"

echo "🚀  Deploying to $TARGET:$REMOTE_DIR …"
echo ""

# Create remote directory structure
ssh "$TARGET" "mkdir -p $REMOTE_DIR/src $REMOTE_DIR/setup $REMOTE_DIR/tools"

# Project source
echo "📦  Copying source files …"
scp src/__init__.py          "$TARGET:$REMOTE_DIR/src/"
scp src/main.py              "$TARGET:$REMOTE_DIR/src/"
scp src/config.py            "$TARGET:$REMOTE_DIR/src/"
scp src/nfc_reader.py        "$TARGET:$REMOTE_DIR/src/"
scp src/spotify_player.py    "$TARGET:$REMOTE_DIR/src/"
scp src/bt_connect.py        "$TARGET:$REMOTE_DIR/src/"

# Setup & services
echo "⚙️   Copying setup files …"
scp requirements.txt         "$TARGET:$REMOTE_DIR/"
scp setup/install.sh         "$TARGET:$REMOTE_DIR/setup/"
scp setup/nfc-player.service "$TARGET:$REMOTE_DIR/setup/"
scp setup/bt-autoconnect.service "$TARGET:$REMOTE_DIR/setup/"

# Config (only if exists locally)
if [ -f config.json ]; then
    echo "📋  Copying config.json → /boot/firmware/ …"
    scp config.json "$TARGET:/boot/firmware/config.json"
else
    echo "⚠️   No local config.json – skipping (use config.json.example as template)"
fi

# Spotify token cache (only if exists locally)
if [ -f spotify_cache ]; then
    echo "🔑  Copying spotify_cache → /boot/firmware/ …"
    scp spotify_cache "$TARGET:/boot/firmware/spotify_cache"
else
    echo "⚠️   No spotify_cache – run 'python tools/spotify_auth.py' first"
fi

echo ""
echo "✅  Deploy complete!"
echo ""
echo "Next steps on the Pi:"
echo "  ssh $TARGET"
echo "  cd $REMOTE_DIR && bash setup/install.sh"
echo "  sudo reboot"
