#!/usr/bin/env bash
# Usage: scripts/rollback.sh <device>   -> IoT Job {"op":"rollback"} (previous release on the device)
set -euo pipefail
exec "$(dirname "$0")/deploy.sh" "${1:?usage: rollback.sh <device>}" --op rollback
