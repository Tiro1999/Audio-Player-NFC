#!/usr/bin/env bash
# Installs a bundle as a new release: extract, venv, provisioning if needed,
# units and wrappers, atomic switch of `current`, restart, health check and
# automatic rollback. --rollback swaps `current` and `previous`.
# Never touches NetworkManager connections.
# Usage: install-release.sh <bundle.tgz> | --rollback
# shellcheck source-path=SCRIPTDIR
set -euo pipefail
shopt -s nullglob
export LC_ALL=C

DEVICE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$DEVICE_DIR/lib.sh"

# Overridable for tests.
INSTALL_ROOT="${NFC_INSTALL_ROOT:-/opt/nfc-player}"
UNIT_DIR="${NFC_UNIT_DIR:-/etc/systemd/system}"
BIN_DIR="${NFC_BIN_DIR:-/usr/local/bin}"
PROFILE_DIR="${NFC_PROFILE_DIR:-/etc/profile.d}"
ETC_DIR="${NFC_ETC_DIR:-/etc/nfc-player}"
SYSTEMCTL="${NFC_SYSTEMCTL:-systemctl}"
SKIP_VENV="${NFC_SKIP_VENV:-0}"
HEALTH_SECONDS="${NFC_HEALTH_SECONDS:-20}"

RELEASES="$INSTALL_ROOT/releases"
VENVS="$INSTALL_ROOT/venvs"
CONFIG_UNIT=nfc-player-config.service

# Prints the version from the bundle's build_info.json (validated).
bundle_version() {
    local info status=0
    info="$(mktemp --suffix=.build_info.json)"
    python3 -I -c 'import shutil, sys, tarfile
try:
    with tarfile.open(sys.argv[1], "r:gz") as tar, open(sys.argv[2], "wb") as out:
        shutil.copyfileobj(tar.extractfile("build_info.json"), out)
except Exception as exc:
    sys.exit(f"cannot read build_info.json: {exc!r}")' "$1" "$info" || status=$?
    if ((status == 0)); then
        build_info "$info" version || status=$?
    fi
    rm -f "$info"
    return "$status"
}

# extract_bundle <bundle> <dir>: the "data" filter refuses absolute paths,
# links leaving the tree and device files.
extract_bundle() {
    rm -rf "$2"
    mkdir -p "$2"
    python3 -I -c 'import sys, tarfile
with tarfile.open(sys.argv[1], "r:gz") as tar:
    tar.extractall(sys.argv[2], filter="data")' "$1" "$2"
}

# Creates the venv for the release's lock file, or reuses a complete one,
# and links releases/<id>/venv to it.
setup_venv() {
    local lock hash venv
    lock="$1/requirements/device.lock"
    [[ -f "$lock" ]] || die "bundle has no requirements/device.lock"
    hash="$(sha256sum "$lock" | cut -c1-12)"
    venv="$VENVS/$hash"
    if [[ "$SKIP_VENV" == 1 ]]; then
        log "Skipping the venv (NFC_SKIP_VENV=1)"
    elif [[ -f "$venv/.complete" ]]; then
        log "Reusing venv $hash"
    else
        log "Creating venv $hash"
        rm -rf "$venv"
        python3 -m venv --system-site-packages "$venv"
        PIP_CONFIG_FILE=/dev/null "$venv/bin/python" -m pip install --no-input --require-hashes \
            --only-binary=:all: --index-url https://pypi.org/simple -r "$lock"
        touch "$venv/.complete"
    fi
    ln -sfn "../../venvs/$hash" "$1/venv"
}

# Runs the release's provision.sh when its provision_rev differs from the one
# recorded by the last successful provisioning.
provision_if_needed() {
    local wanted recorded=""
    wanted="$(build_info "$1/build_info.json" provision_rev)"
    if [[ -f "$ETC_DIR/provision-rev" ]]; then
        recorded="$(<"$ETC_DIR/provision-rev")"
    fi
    if [[ "$wanted" == "$recorded" ]]; then
        log "Provisioning is up to date"
        return 0
    fi
    log "Provisioning revision changed - running provision.sh"
    # 9>&-: daemons started by apt must not inherit the install lock.
    bash "$1/device/provision.sh" 9>&-
}

# Prints where the current/previous link points (releases/<id>), if valid.
link_target() {
    local target
    target="$(readlink "$INSTALL_ROOT/$1")" || return 0
    if [[ "$target" == releases/* && -d "$INSTALL_ROOT/$target" ]]; then
        printf '%s\n' "$target"
    fi
}

# release_files <release> <systemd|bin>: units or wrappers the release ships
# for app and its included modules.
release_files() {
    local module file
    while read -r module; do
        for file in "$1/device/$module/$2"/*; do
            if [[ -f "$file" ]]; then
                printf '%s\n' "$file"
            fi
        done
    done < <(
        echo app
        build_info "$1/build_info.json" modules
    )
}

# Units of a release with an [Install] section.
installable_units() {
    local file
    while read -r file; do
        if grep -qx '\[Install\]' "$file"; then
            printf '%s\n' "${file##*/}"
        fi
    done < <(release_files "$1" systemd)
}

# Long-running services of a release: every .service except Type=oneshot.
long_running_services() {
    local file
    while read -r file; do
        if [[ "$file" == *.service ]] && ! grep -qx 'Type=oneshot' "$file"; then
            printf '%s\n' "${file##*/}"
        fi
    done < <(release_files "$1" systemd)
}

# Disables and deletes a unit. A oneshot may be the updater that runs this
# script, so it is never stopped.
remove_unit() {
    if grep -qx 'Type=oneshot' "$UNIT_DIR/$1"; then
        "$SYSTEMCTL" disable "$1" || true
    else
        "$SYSTEMCTL" disable --now "$1" || true
    fi
    rm -f "$UNIT_DIR/$1"
    log "removed $UNIT_DIR/$1"
}

# Installs the units (service user's UID filled in), wrappers and login
# banner of a release, removes units and wrappers that only other releases
# ship (excluded modules), then reloads systemd.
install_device_files() {
    local release="$1" uid="${NFC_UID:-}" file name rendered other
    local -A shipped=()
    if [[ -z "$uid" ]]; then
        uid="$(id -u nfc-player)" || die "service user nfc-player is missing - run provision.sh"
    fi
    [[ "$uid" =~ ^[0-9]+$ ]] || die "invalid UID: $uid"
    mkdir -p "$UNIT_DIR" "$BIN_DIR" "$PROFILE_DIR"

    rendered="$(mktemp)"
    while read -r file; do
        name="${file##*/}"
        sed "s/@NFC_UID@/$uid/g" "$file" >"$rendered"
        install_file "$rendered" "$UNIT_DIR/$name" 0644
        shipped[$name]=1
    done < <(release_files "$release" systemd)
    rm -f "$rendered"
    while read -r file; do
        name="${file##*/}"
        install_file "$file" "$BIN_DIR/$name" 0755
        shipped[$name]=1
    done < <(release_files "$release" bin)
    install_file "$release/device/app/profile.d/nfc-player.sh" "$PROFILE_DIR/nfc-player.sh" 0644

    for other in "$RELEASES"/*/; do
        other="${other%/}"
        [[ "$other" != "$release" && "$other" != *.tmp ]] || continue
        while read -r file; do
            name="${file##*/}"
            if [[ -z "${shipped[$name]:-}" && -f "$UNIT_DIR/$name" ]]; then
                remove_unit "$name"
            fi
        done < <(release_files "$other" systemd)
        while read -r file; do
            name="${file##*/}"
            if [[ -z "${shipped[$name]:-}" && -f "$BIN_DIR/$name" ]]; then
                rm -f "$BIN_DIR/$name"
                log "removed $BIN_DIR/$name"
            fi
        done < <(release_files "$other" bin)
    done
    "$SYSTEMCTL" daemon-reload
}

# Enables the units of a release, runs the config import first, then
# restarts the long-running services. Timers are only enabled: started
# now, the update timer would fire at once.
restart_services() {
    local -a units services
    mapfile -t units < <(installable_units "$1")
    mapfile -t services < <(long_running_services "$1")
    "$SYSTEMCTL" enable "${units[@]}" || return 1
    if ! "$SYSTEMCTL" start "$CONFIG_UNIT"; then
        log "WARNING: config import failed - see: journalctl -u $CONFIG_UNIT"
    fi
    "$SYSTEMCTL" restart "${services[@]}"
}

# True when every long-running service stays active without automatic
# restarts for HEALTH_SECONDS.
health_check() {
    local service state restarts deadline
    local -a services
    local -A baseline=()
    mapfile -t services < <(long_running_services "$1")
    for service in "${services[@]}"; do
        baseline[$service]="$("$SYSTEMCTL" show -p NRestarts --value "$service")"
    done
    deadline=$((SECONDS + HEALTH_SECONDS))
    while true; do
        for service in "${services[@]}"; do
            state="$("$SYSTEMCTL" show -p ActiveState --value "$service")"
            restarts="$("$SYSTEMCTL" show -p NRestarts --value "$service")"
            if [[ "$state" != active || "$restarts" != "${baseline[$service]}" ]]; then
                log "Health check failed: $service is $state (restarts ${baseline[$service]} -> $restarts)" \
                    "- see: journalctl -u $service"
                return 1
            fi
        done
        if ((SECONDS >= deadline)); then
            return 0
        fi
        sleep 1
    done
}

# Keeps current, previous and the newest other release; then removes the
# venvs no remaining release links to.
prune() {
    local current previous name link venv spare_kept=0
    local -a names
    local -A used=()
    current="$(link_target current)"
    previous="$(link_target previous)"
    mapfile -t names < <(find "$RELEASES" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort -r)
    for name in "${names[@]}"; do
        if [[ "releases/$name" == "$current" || "releases/$name" == "$previous" ]]; then
            continue
        fi
        if [[ "$spare_kept" == 0 && "$name" != *.tmp ]]; then
            spare_kept=1
            continue
        fi
        rm -rf "${RELEASES:?}/$name"
        log "removed release $name"
    done
    for link in "$RELEASES"/*/venv; do
        if [[ -L "$link" ]]; then
            venv="$(readlink "$link")"
            used[${venv##*/}]=1
        fi
    done
    for venv in "$VENVS"/*/; do
        venv="${venv%/}"
        if [[ -z "${used[${venv##*/}]:-}" ]]; then
            rm -rf "$venv"
            log "removed venv ${venv##*/}"
        fi
    done
}

install_bundle() {
    local bundle="$1" version release_id release old_current old_previous
    [[ -f "$bundle" ]] || die "bundle not found: $bundle"
    version="$(bundle_version "$bundle")" || die "no valid build_info.json in $bundle"
    release_id="$(date -u +%Y%m%d-%H%M%S)-$version"
    release="$RELEASES/$release_id"
    [[ ! -e "$release" ]] || die "release $release_id exists already"
    log "Installing release $release_id"

    mkdir -p "$RELEASES" "$VENVS"
    extract_bundle "$bundle" "$release.tmp"
    mv -T "$release.tmp" "$release"
    build_info "$release/build_info.json" modules >/dev/null
    setup_venv "$release"
    python3 -I -m compileall -q "$release/src" || die "compiling $release/src failed"
    provision_if_needed "$release"
    install_device_files "$release"

    old_current="$(link_target current)"
    old_previous="$(link_target previous)"
    switch_link "$INSTALL_ROOT/current" "releases/$release_id"
    if [[ -n "$old_current" ]]; then
        switch_link "$INSTALL_ROOT/previous" "$old_current"
    fi

    if restart_services "$release" && health_check "$release"; then
        prune
        log "Release $release_id is active"
        return 0
    fi
    [[ -n "$old_current" ]] || die "release $release_id is unhealthy and there is no release to return to"
    log "Release $release_id is unhealthy - returning to ${old_current#releases/}"
    install_device_files "$INSTALL_ROOT/$old_current"
    switch_link "$INSTALL_ROOT/current" "$old_current"
    if [[ -n "$old_previous" ]]; then
        switch_link "$INSTALL_ROOT/previous" "$old_previous"
    else
        rm -f "$INSTALL_ROOT/previous"
    fi
    restart_services "$INSTALL_ROOT/$old_current" || log "WARNING: restart after the rollback failed"
    die "release $release_id failed its health check and was rolled back"
}

rollback() {
    local current previous
    current="$(link_target current)"
    previous="$(link_target previous)"
    [[ -n "$previous" ]] || die "no previous release to roll back to"
    log "Rolling back to ${previous#releases/}"
    install_device_files "$INSTALL_ROOT/$previous"
    switch_link "$INSTALL_ROOT/current" "$previous"
    if [[ -n "$current" ]]; then
        switch_link "$INSTALL_ROOT/previous" "$current"
    fi
    if restart_services "$INSTALL_ROOT/$previous" && health_check "$INSTALL_ROOT/$previous"; then
        log "Release ${previous#releases/} is active"
    else
        die "release ${previous#releases/} is unhealthy - check: nfc-status"
    fi
}

(($# == 1)) || die "usage: install-release.sh <bundle.tgz> | --rollback"
[[ "$HEALTH_SECONDS" =~ ^[0-9]+$ ]] || die "NFC_HEALTH_SECONDS must be a number"
require_root
mkdir -p "$INSTALL_ROOT"
# One install at a time (the updater and a manual deploy may overlap).
exec 9>"$INSTALL_ROOT/.install.lock"
flock -n 9 || die "another install-release.sh is running"

if [[ "$1" == --rollback ]]; then
    rollback
else
    install_bundle "$1"
fi
