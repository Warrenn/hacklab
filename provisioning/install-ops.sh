#!/usr/bin/env bash
# Install/upgrade the ops agent on a Pi. Run from the maintainer's machine after
# scripts/provision-device.sh. Idempotent. Needs root ssh to the Pi (Tailscale
# SSH: ssh root@hacklab) or any user with passwordless sudo.
# Usage: provisioning/install-ops.sh <device> [ssh-target]   e.g. pi3 root@hacklab
set -euo pipefail
device=${1:?usage: install-ops.sh <device> [ssh-target]}
target=${2:-root@hacklab}
root=$(cd "$(dirname "$0")/.." && pwd)
local_dir="$root/provisioning/local/$device"
[ -f "$local_dir/cert.pem" ] || { echo "run scripts/provision-device.sh $device first" >&2; exit 1; }

tmp=$(ssh "$target" 'mktemp -d')
scp -q "$root"/ops/*.py "$root/ops/requirements.txt" "$root/provisioning/install-ops-local.sh" \
    "$local_dir/cert.pem" "$local_dir/private.key" "$local_dir/AmazonRootCA1.pem" "$target:$tmp/"
# shellcheck disable=SC2029  # the env assignments are meant to expand here
ssh "$target" "sudo=; [ \"\$(id -u)\" = 0 ] || sudo=sudo; \
  \$sudo env HACKLAB_THING=hacklab-$device HACKLAB_IOT_ENDPOINT=$(cat "$local_dir/endpoint.txt") HACKLAB_SRC=$tmp \
  bash $tmp/install-ops-local.sh $tmp && \$sudo rm -rf $tmp && systemctl --no-pager --lines=3 status hacklab-ops.service"
echo "installed; check with scripts/status.sh $device"
