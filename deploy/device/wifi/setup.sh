#!/usr/bin/env bash
# Provisioning for wifi: polkit rule, so the service user can manage
# NetworkManager profiles without sudo.
# shellcheck source-path=SCRIPTDIR/..
set -euo pipefail

MODULE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$MODULE_DIR/../lib.sh"
require_root

log "polkit rule for NetworkManager"
mkdir -p /etc/polkit-1/rules.d
install_file "$MODULE_DIR/50-nfc-player-networkmanager.rules" \
    /etc/polkit-1/rules.d/50-nfc-player-networkmanager.rules 0644
