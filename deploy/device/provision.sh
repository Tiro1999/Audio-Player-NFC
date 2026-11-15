#!/usr/bin/env bash
# Provisioning (OS setup): base/setup.sh, then the setup.sh of every module
# this bundle includes. Idempotent; runs as root from an extracted bundle.
# Usage: provision.sh [--os-upgrade] [--usb-gadget]
#        [--hold-wpasupplicant|--release-wpasupplicant] [--i2c-baudrate N] [--ssh-hardening]
# shellcheck source-path=SCRIPTDIR
set -euo pipefail

DEVICE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$DEVICE_DIR/lib.sh"

usage() {
    die "usage: provision.sh [--os-upgrade] [--usb-gadget]" \
        "[--hold-wpasupplicant|--release-wpasupplicant] [--i2c-baudrate N] [--ssh-hardening]"
}

# Options for the setup scripts; unset flags keep the current OS state.
export PROVISION_OS_UPGRADE=0 PROVISION_USB_GADGET=0 PROVISION_SSH_HARDENING=0
export PROVISION_WPASUPPLICANT=keep PROVISION_I2C_BAUDRATE=""
while (($#)); do
    case "$1" in
        --os-upgrade) PROVISION_OS_UPGRADE=1 ;;
        --usb-gadget) PROVISION_USB_GADGET=1 ;;
        --ssh-hardening) PROVISION_SSH_HARDENING=1 ;;
        --hold-wpasupplicant)
            [[ "$PROVISION_WPASUPPLICANT" != release ]] || usage
            PROVISION_WPASUPPLICANT=hold
            ;;
        --release-wpasupplicant)
            [[ "$PROVISION_WPASUPPLICANT" != hold ]] || usage
            PROVISION_WPASUPPLICANT=release
            ;;
        --i2c-baudrate)
            [[ "${2:-}" =~ ^[1-9][0-9]{3,6}$ ]] || die "invalid I2C baudrate: ${2:-missing} (Hz, e.g. 100000)"
            PROVISION_I2C_BAUDRATE="$2"
            shift
            ;;
        *) usage ;;
    esac
    shift
done

BUILD_INFO="$(dirname "$DEVICE_DIR")/build_info.json"
[[ -f "$BUILD_INFO" ]] || die "$BUILD_INFO not found - run provision.sh from an extracted bundle"
require_root
revision="$(build_info "$BUILD_INFO" provision_rev)"

log "Provisioning revision ${revision:0:12}"
bash "$DEVICE_DIR/base/setup.sh"
for setup in "$DEVICE_DIR"/*/setup.sh; do
    module="$(basename "$(dirname "$setup")")"
    if [[ "$module" != base ]] && has_module "$module"; then
        bash "$setup"
    fi
done

printf '%s\n' "$revision" | write_file "${NFC_ETC_DIR:-/etc/nfc-player}/provision-rev" 0644
log "Provisioning done - reboot if a step above asked for it"
