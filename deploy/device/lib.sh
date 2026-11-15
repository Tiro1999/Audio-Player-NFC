# Helpers for the device scripts; sourced, never executed.
# shellcheck shell=bash

# Log prefix: the module for <module>/setup.sh, else the script name.
LOG_NAME="$(basename "$0" .sh)"
if [[ "$LOG_NAME" == setup ]]; then
    LOG_NAME="$(basename "$(dirname "$0")")"
fi

log() {
    printf '%s: %s\n' "$LOG_NAME" "$*"
}

die() {
    log "ERROR: $*" >&2
    exit 1
}

# NFC_SKIP_ROOT_CHECK=1 lets tests run the scripts against temp directories.
require_root() {
    if [[ "${NFC_SKIP_ROOT_CHECK:-0}" != 1 && "$EUID" -ne 0 ]]; then
        die "run as root (sudo)"
    fi
}

# build_info <build_info.json> <version|provision_rev|modules>: prints the
# validated value (modules one per line) or fails with a message.
build_info() {
    python3 -I - "$1" "$2" <<'EOF'
import json
import re
import sys

path, key = sys.argv[1], sys.argv[2]
rules = {
    "version": r"[0-9A-Za-z][0-9A-Za-z._+-]{0,63}",
    "provision_rev": r"[0-9a-f]{64}",
    "modules": r"[a-z][a-z0-9_]{0,31}",
}
try:
    with open(path, encoding="utf-8") as file:
        value = json.load(file)[key]
except (OSError, ValueError, KeyError, TypeError) as exc:
    sys.exit(f"{path}: no {key}: {exc}")
if key == "modules" and not isinstance(value, list):
    sys.exit(f"{path}: modules is not a list")
values = value if key == "modules" else [value]
for item in values:
    if not isinstance(item, str) or not re.fullmatch(rules[key], item):
        sys.exit(f"{path}: invalid {key}: {item!r}")
for item in values:
    print(item)
EOF
}

# has_module <name>: true when $BUILD_INFO lists the module.
has_module() {
    build_info "$BUILD_INFO" modules | grep -xF -- "$1" >/dev/null
}

# install_file <src> <dst> <mode> [owner:group]: writes dst (atomic rename)
# only when content, mode or owner differ. CHANGED=1 if it wrote, else 0.
# shellcheck disable=SC2034  # CHANGED is read by the calling scripts
install_file() {
    local src="$1" dst="$2" mode="$3" owner="${4:-}" tmp
    CHANGED=0
    if [[ -f "$dst" ]] && cmp -s "$src" "$dst" \
        && [[ "$(stat -c '%a' "$dst")" == "${mode#0}" ]] \
        && [[ -z "$owner" || "$(stat -c '%U:%G' "$dst")" == "$owner" ]]; then
        return 0
    fi
    tmp="$(dirname "$dst")/.$(basename "$dst").tmp"
    install -m "$mode" "$src" "$tmp"
    if [[ -n "$owner" ]]; then
        chown "$owner" "$tmp"
    fi
    mv -f "$tmp" "$dst"
    CHANGED=1
    log "updated $dst"
}

# write_file <dst> <mode> [owner:group]: install_file with content from stdin.
write_file() {
    local tmp
    tmp="$(mktemp)"
    cat >"$tmp"
    install_file "$tmp" "$@"
    rm -f "$tmp"
}

# switch_link <link> <target>: points the symlink at target (atomic rename).
switch_link() {
    ln -sfn "$2" "$1.new"
    mv -Tf "$1.new" "$1"
}
