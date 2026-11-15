#!/usr/bin/env bash
# Provisioning base: packages, service user, directories, headless audio
# session, journald, watchdog, unattended-upgrades and the optional flags of
# provision.sh (PROVISION_*). Idempotent.
# shellcheck source-path=SCRIPTDIR/..
set -euo pipefail

# shellcheck source=lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/../lib.sh"
require_root
export DEBIAN_FRONTEND=noninteractive

SERVICE_USER=nfc-player
STATE_DIR=/var/lib/nfc-player

log "Updating the package lists"
apt-get update
# Before any install or upgrade, so a held wpasupplicant stays untouched.
case "${PROVISION_WPASUPPLICANT:-keep}" in
    hold) apt-mark hold wpasupplicant ;;
    release) apt-mark unhold wpasupplicant ;;
esac

log "Installing packages"
apt-get install -y -o Dpkg::Options::=--force-confold \
    python3-venv python3-libgpiod i2c-tools bluez pipewire pipewire-pulse wireplumber \
    libspa-0.2-bluetooth pulseaudio-utils unattended-upgrades libasound2t64
if [[ "${PROVISION_OS_UPGRADE:-0}" == 1 ]]; then
    log "Upgrading the OS"
    DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::=--force-confold full-upgrade
fi

log "Service user $SERVICE_USER"
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    adduser --system --group --home "$STATE_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi
usermod -a -G i2c,bluetooth,audio "$SERVICE_USER"

log "Directories"
install -d -o root -g root -m 0755 /opt/nfc-player /opt/nfc-player/releases \
    /opt/nfc-player/venvs /opt/nfc-player/receiver
install -d -o root -g "$SERVICE_USER" -m 0750 /etc/nfc-player
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$STATE_DIR"

log "Audio: PipeWire session of $SERVICE_USER, headless WirePlumber"
for dir in .config .config/wireplumber .config/wireplumber/wireplumber.conf.d; do
    install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0755 "$STATE_DIR/$dir"
done
write_file "$STATE_DIR/.config/wireplumber/wireplumber.conf.d/80-nfc-player-headless.conf" 0644 \
    "$SERVICE_USER:$SERVICE_USER" <<'EOF'
# Headless device: there is no logind seat, so BlueZ must not wait for one.
wireplumber.profiles = {
  main = {
    monitor.bluez.seat-monitoring = disabled
  }
}
EOF
wireplumber_changed="$CHANGED"
loginctl enable-linger "$SERVICE_USER"
systemctl start "user@$(id -u "$SERVICE_USER").service"
systemctl --user -M "$SERVICE_USER@" enable --now pipewire.socket pipewire-pulse.socket wireplumber.service
if [[ "$wireplumber_changed" == 1 ]]; then
    systemctl --user -M "$SERVICE_USER@" restart wireplumber.service
fi

log "journald: persistent, at most 64M"
mkdir -p /etc/systemd/journald.conf.d
write_file /etc/systemd/journald.conf.d/50-nfc-player.conf 0644 <<'EOF'
[Journal]
Storage=persistent
SystemMaxUse=64M
EOF
if [[ "$CHANGED" == 1 ]]; then
    systemctl restart systemd-journald
    journalctl --flush
fi

log "Hardware watchdog"
mkdir -p /etc/systemd/system.conf.d
write_file /etc/systemd/system.conf.d/50-nfc-player-watchdog.conf 0644 <<'EOF'
[Manager]
RuntimeWatchdogSec=15s
EOF
if [[ "$CHANGED" == 1 ]]; then
    log "Watchdog: active after the next reboot"
fi

log "unattended-upgrades"
write_file /etc/apt/apt.conf.d/20auto-upgrades 0644 <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF
blacklist=""
if [[ -n "$(apt-mark showhold wpasupplicant)" ]]; then
    blacklist='Unattended-Upgrade::Package-Blacklist { "wpasupplicant"; };'
fi
write_file /etc/apt/apt.conf.d/52nfc-player-unattended 0644 <<EOF
// nfc-player: kernel and firmware from the Raspberry Pi archive as well;
// reboot at 04:00 when an update needs it.
Unattended-Upgrade::Origins-Pattern {
    "site=archive.raspberrypi.com";
};
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "04:00";
$blacklist
EOF
if ! unattended-upgrade --dry-run --verbose; then
    log "WARNING: unattended-upgrade --dry-run failed - see the output above"
fi

if [[ "${PROVISION_USB_GADGET:-0}" == 1 ]]; then
    log "USB gadget: SSH over the data cable"
    apt-get install -y rpi-usb-gadget
    rpi-usb-gadget on
    log "USB gadget: reboot required"
fi

if [[ "${PROVISION_SSH_HARDENING:-0}" == 1 ]]; then
    log "SSH: key login only, no root login"
    sshd_dropin=/etc/ssh/sshd_config.d/10-nfc-player.conf
    mkdir -p /etc/ssh/sshd_config.d
    write_file "$sshd_dropin" 0644 <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF
    if ! sshd -t; then
        rm -f "$sshd_dropin"
        die "sshd config test failed - drop-in removed, ssh left as it was"
    fi
    # reload keeps open sessions alive.
    systemctl reload ssh
fi
