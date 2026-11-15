#!/usr/bin/env bash
# Provisioning for spotify: the pinned go-librespot receiver (checksum
# verified) and its state directory.
# shellcheck source-path=SCRIPTDIR/..
set -euo pipefail

MODULE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$MODULE_DIR/../lib.sh"
require_root

RECEIVER_ROOT=/opt/nfc-player/receiver

version="" url="" sha256=""
while IFS='=' read -r key value || [[ -n "$key" ]]; do
    case "$key" in
        VERSION) version="$value" ;;
        URL) url="$value" ;;
        SHA256) sha256="$value" ;;
    esac
done <"$MODULE_DIR/go-librespot.pin"
[[ "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "go-librespot.pin: invalid VERSION"
[[ "$url" == "https://github.com/devgianlu/go-librespot/releases/download/$version/"* ]] \
    || die "go-librespot.pin: invalid URL"
[[ "$sha256" =~ ^[0-9a-f]{64}$ ]] || die "go-librespot.pin: invalid SHA256"

binary="$RECEIVER_ROOT/go-librespot-$version"
if [[ -x "$binary" ]]; then
    log "go-librespot $version is installed"
else
    log "Downloading go-librespot $version"
    work="$(mktemp -d)"
    trap 'rm -rf "$work"' EXIT
    python3 -I -c 'import shutil, sys, urllib.request
with urllib.request.urlopen(sys.argv[1], timeout=60) as response, open(sys.argv[2], "wb") as out:
    shutil.copyfileobj(response, out)' "$url" "$work/go-librespot.tar.gz"
    (cd "$work" && printf '%s  go-librespot.tar.gz\n' "$sha256" | sha256sum -c -)
    tar -xzf "$work/go-librespot.tar.gz" -C "$work" --no-same-owner
    [[ -f "$work/go-librespot" ]] || die "the archive has no go-librespot binary"
    install_file "$work/go-librespot" "$binary" 0755 root:root
fi
switch_link "$RECEIVER_ROOT/go-librespot" "go-librespot-$version"
install -d -o nfc-player -g nfc-player -m 0700 /var/lib/nfc-player/receiver
