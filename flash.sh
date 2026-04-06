#!/usr/bin/env bash
# ===========================================================================
#  flash.sh – Deploy all project files to the Pi and reboot
#  Reads PI_IP and PI_USER from .env
#
#  Usage:
#    bash flash.sh              # deploy + reboot
#    bash flash.sh --no-reboot  # deploy only (dev iterations)
# ===========================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── Load .env ──────────────────────────────────────────────────────────────
if [ ! -f .env ]; then
    echo "❌  .env not found. Copy .env.example → .env and fill in your values."
    exit 1
fi
set -a; source .env; set +a

: "${PI_IP:?PI_IP not set in .env}"
: "${PI_USER:?PI_USER not set in .env}"

TARGET="$PI_USER@$PI_IP"
REMOTE_DIR="~/nfc-player"

# ── Parse flags ────────────────────────────────────────────────────────────
DO_REBOOT=true
for arg in "$@"; do
    case "$arg" in
        --no-reboot) DO_REBOOT=false ;;
        *) echo "Unknown flag: $arg"; exit 1 ;;
    esac
done

echo "========================================"
echo "  🚀  Flashing to $TARGET"
echo "  Remote dir: $REMOTE_DIR"
echo "  Reboot: $DO_REBOOT"
echo "========================================"
echo ""

# ── Create remote directories ─────────────────────────────────────────────
echo "📁  Creating remote directories …"
ssh "$TARGET" "mkdir -p $REMOTE_DIR/src $REMOTE_DIR/setup $REMOTE_DIR/tools $REMOTE_DIR/tests"

# ── Copy source files ─────────────────────────────────────────────────────
echo "📦  Copying source files …"
scp src/__init__.py        "$TARGET:$REMOTE_DIR/src/"
scp src/main.py            "$TARGET:$REMOTE_DIR/src/"
scp src/config.py          "$TARGET:$REMOTE_DIR/src/"
scp src/nfc_reader.py      "$TARGET:$REMOTE_DIR/src/"
scp src/spotify_player.py  "$TARGET:$REMOTE_DIR/src/"
scp src/bt_connect.py      "$TARGET:$REMOTE_DIR/src/"

# ── Copy setup files ──────────────────────────────────────────────────────
echo "⚙️   Copying setup & tools …"
scp requirements.txt               "$TARGET:$REMOTE_DIR/"
scp setup/install.sh               "$TARGET:$REMOTE_DIR/setup/"
scp setup/nfc-player.service       "$TARGET:$REMOTE_DIR/setup/"
scp setup/bt-autoconnect.service   "$TARGET:$REMOTE_DIR/setup/"
scp tools/bt_tools.py              "$TARGET:$REMOTE_DIR/tools/"
scp tools/spotify_auth.py          "$TARGET:$REMOTE_DIR/tools/"

# ── Config (only if local file exists) ─────────────────────────────────────
if [ -f config.json ]; then
    echo "📋  Copying config.json → /boot/firmware/ …"
    scp config.json "$TARGET:/boot/firmware/config.json"
else
    echo "⚠️   No local config.json – skipping (use config.json.example as template)"
fi

# ── Spotify token cache (only if local file exists) ────────────────────────
if [ -f spotify_cache ]; then
    echo "🔑  Copying spotify_cache → /boot/firmware/ …"
    scp spotify_cache "$TARGET:/boot/firmware/spotify_cache"
fi

echo ""
echo "✅  Files transferred!"

# ── Reboot ─────────────────────────────────────────────────────────────────
if [ "$DO_REBOOT" = true ]; then
    echo "🔄  Rebooting Pi …"
    ssh "$TARGET" "sudo reboot" || true
    echo "    Pi is rebooting. Wait ~30s, then: ssh $TARGET"
else
    echo "ℹ️   Skipping reboot (--no-reboot). Restart services manually:"
    echo "    ssh $TARGET \"sudo systemctl restart nfc-player bt-autoconnect\""
fi
