#!/usr/bin/env bash
# Provisioning for nfc: I2C on; optional I2C bus speed for the reader
# (PROVISION_I2C_BAUDRATE, needs a reboot).
# shellcheck source-path=SCRIPTDIR/..
set -euo pipefail

# shellcheck source=lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/../lib.sh"
require_root

CONFIG_TXT=/boot/firmware/config.txt

log "Enabling I2C"
raspi-config nonint do_i2c 0

baudrate="${PROVISION_I2C_BAUDRATE:-}"
if [[ -n "$baudrate" ]]; then
    [[ "$baudrate" =~ ^[0-9]+$ ]] || die "invalid I2C baudrate: $baudrate"
    line="dtparam=i2c_arm_baudrate=$baudrate"
    if grep -qxF -- "$line" "$CONFIG_TXT"; then
        log "I2C baudrate is $baudrate already"
    else
        if grep -q '^dtparam=i2c_arm_baudrate=' "$CONFIG_TXT"; then
            sed -i "s/^dtparam=i2c_arm_baudrate=.*/$line/" "$CONFIG_TXT"
        else
            printf '\n[all]\n%s\n' "$line" >>"$CONFIG_TXT"
        fi
        log "I2C baudrate set to $baudrate - reboot required"
    fi
fi
