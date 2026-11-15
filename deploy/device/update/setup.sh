#!/usr/bin/env bash
# Provisioning for update: nothing OS-level; its units come with each release.
# shellcheck source-path=SCRIPTDIR/..
set -euo pipefail

# shellcheck source=lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/../lib.sh"

log "Nothing to provision - the update timer comes with the release"
