#!/usr/bin/env bash
# Provisioning for bluetooth: radio unblocked, bluetooth service running.
# shellcheck source-path=SCRIPTDIR/..
set -euo pipefail

# shellcheck source=lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/../lib.sh"
require_root

log "Unblocking and enabling Bluetooth"
rfkill unblock bluetooth
systemctl enable --now bluetooth
