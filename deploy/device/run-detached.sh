#!/usr/bin/env bash
# Runs a command as a transient systemd unit, so it survives a dropped SSH
# session; prints the unit's log meanwhile and exits with its exit code.
# Usage: run-detached.sh <unit-name> <command...>
# shellcheck source-path=SCRIPTDIR
set -euo pipefail

# shellcheck source=lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

(($# >= 2)) || die "usage: run-detached.sh <unit-name> <command...>"
unit="$1"
shift
[[ "$unit" =~ ^nfc-player-[a-z0-9-]+$ ]] || die "invalid unit name: $unit (expected nfc-player-...)"
require_root

rc_file="${NFC_RUN_DIR:-/run}/$unit.rc"
if systemctl is-active --quiet "$unit"; then
    die "$unit is still running - follow it with: journalctl -fu $unit"
fi
rm -f "$rc_file"

since="$(date '+%Y-%m-%d %H:%M:%S')"
# --collect drops the unit's own result at once, so the command's exit code
# goes to rc_file. --expand-environment=no passes the arguments verbatim.
# shellcheck disable=SC2016  # the inner bash expands "$@", $? and $NFC_RC_FILE
systemd-run --unit="$unit" --collect --expand-environment=no \
    --property=TimeoutStartSec=infinity \
    --setenv=DEBIAN_FRONTEND=noninteractive --setenv=NFC_RC_FILE="$rc_file" \
    -- /bin/bash -c '"$@"; rc=$?; echo "$rc" >"$NFC_RC_FILE"; exit "$rc"' run-detached "$@"
log "$unit started - after a dropped connection follow it with: journalctl -fu $unit"

journalctl -f -o cat -u "$unit" --since "$since" &
journal_pid=$!
trap 'kill "$journal_pid" 2>/dev/null || true' EXIT

while [[ "$(systemctl show -p ActiveState --value "$unit")" =~ ^(active|activating|deactivating|reloading)$ ]]; do
    sleep 1
done
sleep 1 # let journalctl print the last lines

[[ -s "$rc_file" ]] || die "$unit ended without an exit code (stopped or killed)"
rc="$(<"$rc_file")"
rm -f "$rc_file"
[[ "$rc" =~ ^[0-9]+$ ]] || die "$unit left an invalid exit code: $rc"
log "$unit finished with exit code $rc"
exit "$rc"
