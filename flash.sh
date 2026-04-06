#!/usr/bin/env bash
# ===========================================================================
#  flash.sh – Deploy all project files to the Pi and reboot
#  Reads PI_IP and PI_USER from .env
#  Uses SSH multiplexing: enter password ONCE, all transfers reuse it.
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

# Strip Windows \r from sourced values
PI_IP="$(echo "$PI_IP" | tr -d '\r')"
PI_USER="$(echo "$PI_USER" | tr -d '\r')"

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

# ── SSH multiplexing (one password prompt for everything) ──────────────────
CTRL_SOCKET="/tmp/flash-ssh-$$"
SSH_OPTS="-o ControlMaster=auto -o ControlPath=$CTRL_SOCKET -o ControlPersist=60"

cleanup() { ssh -O exit -o ControlPath="$CTRL_SOCKET" "$TARGET" 2>/dev/null || true; }
trap cleanup EXIT

echo "🔑  Connecting to $TARGET …"
ssh $SSH_OPTS -fN "$TARGET"
echo "    Connection established (password won't be asked again)"
echo ""

# ── Create remote directories ─────────────────────────────────────────────
echo "📁  Creating remote directories …"
ssh $SSH_OPTS "$TARGET" "mkdir -p $REMOTE_DIR/src $REMOTE_DIR/setup $REMOTE_DIR/tools $REMOTE_DIR/tests"

# ── Copy source files ─────────────────────────────────────────────────────
echo "📦  Copying source files …"
scp $SSH_OPTS src/__init__.py        "$TARGET:$REMOTE_DIR/src/"
scp $SSH_OPTS src/main.py            "$TARGET:$REMOTE_DIR/src/"
scp $SSH_OPTS src/config.py          "$TARGET:$REMOTE_DIR/src/"
scp $SSH_OPTS src/nfc_reader.py      "$TARGET:$REMOTE_DIR/src/"
scp $SSH_OPTS src/spotify_player.py  "$TARGET:$REMOTE_DIR/src/"
scp $SSH_OPTS src/bt_connect.py      "$TARGET:$REMOTE_DIR/src/"
scp $SSH_OPTS src/logger.py          "$TARGET:$REMOTE_DIR/src/"

# ── Copy setup files ──────────────────────────────────────────────────────
echo "⚙️   Copying setup & tools …"
scp $SSH_OPTS requirements.txt               "$TARGET:$REMOTE_DIR/"
scp $SSH_OPTS setup/install.sh               "$TARGET:$REMOTE_DIR/setup/"
scp $SSH_OPTS setup/nfc-player.service       "$TARGET:$REMOTE_DIR/setup/"
scp $SSH_OPTS setup/bt-autoconnect.service   "$TARGET:$REMOTE_DIR/setup/"
scp $SSH_OPTS tools/bt_tools.py              "$TARGET:$REMOTE_DIR/tools/"
scp $SSH_OPTS tools/wifi_tools.py            "$TARGET:$REMOTE_DIR/tools/"
scp $SSH_OPTS tools/nfc_test.py              "$TARGET:$REMOTE_DIR/tools/"
scp $SSH_OPTS tools/spotify_auth.py          "$TARGET:$REMOTE_DIR/tools/"

# ── Config (only if local file exists) ─────────────────────────────────────
if [ -f config.json ]; then
    echo "📋  Copying config.json → /boot/firmware/ …"
    scp $SSH_OPTS config.json "$TARGET:/boot/firmware/config.json"
else
    echo "⚠️   No local config.json – skipping (use config.json.example as template)"
fi

# ── Spotify token cache (only if local file exists) ────────────────────────
if [ -f spotify_cache ]; then
    echo "🔑  Copying spotify_cache → /boot/firmware/ …"
    scp $SSH_OPTS spotify_cache "$TARGET:/boot/firmware/spotify_cache"
fi

echo ""
echo "✅  Files transferred!"

# ── Reboot ─────────────────────────────────────────────────────────────────
if [ "$DO_REBOOT" = true ]; then
    echo "🔄  Rebooting Pi …"
    ssh $SSH_OPTS "$TARGET" "sudo reboot" || true
    echo "    Pi is rebooting. Wait ~30s, then: ssh $TARGET"
else
    echo "ℹ️   Skipping reboot (--no-reboot). Restart services manually:"
    echo "    ssh $TARGET \"sudo systemctl restart nfc-player bt-autoconnect\""
fi
