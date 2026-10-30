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
scp -q "$root/ops/agent.py" "$root/ops/requirements.txt" \
    "$local_dir/cert.pem" "$local_dir/private.key" "$local_dir/AmazonRootCA1.pem" "$target:$tmp/"

# shellcheck disable=SC2029  # the env assignments are meant to expand here
ssh "$target" "HACKLAB_THING=hacklab-$device HACKLAB_IOT_ENDPOINT=$(cat "$local_dir/endpoint.txt") TMP=$tmp bash -s" <<'REMOTE'
set -euo pipefail
sudo=; [ "$(id -u)" = 0 ] || sudo=sudo
$sudo bash -euo pipefail <<EOS
id -u hacklab-ops >/dev/null 2>&1 || useradd --system --home /opt/hacklab/ops --shell /usr/sbin/nologin hacklab-ops
mkdir -p /opt/hacklab/ops /opt/hacklab/data/iot
install -m 644 "$TMP/agent.py" "$TMP/requirements.txt" /opt/hacklab/ops/
install -o hacklab-ops -g hacklab-ops -m 600 "$TMP/cert.pem" "$TMP/private.key" "$TMP/AmazonRootCA1.pem" /opt/hacklab/data/iot/
[ -x /opt/hacklab/ops/venv/bin/python ] || python3 -m venv /opt/hacklab/ops/venv
/opt/hacklab/ops/venv/bin/pip install -q --disable-pip-version-check -r /opt/hacklab/ops/requirements.txt
printf 'HACKLAB_THING=%s\nHACKLAB_IOT_ENDPOINT=%s\nHACKLAB_IOT_DIR=/opt/hacklab/data/iot\n' "$HACKLAB_THING" "$HACKLAB_IOT_ENDPOINT" > /etc/default/hacklab-ops
cat > /etc/systemd/system/hacklab-ops.service <<UNIT
[Unit]
Description=hacklab ops agent (IoT shadow heartbeat)
After=network-online.target
Wants=network-online.target

[Service]
User=hacklab-ops
EnvironmentFile=/etc/default/hacklab-ops
ExecStart=/opt/hacklab/ops/venv/bin/python /opt/hacklab/ops/agent.py
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now hacklab-ops.service
systemctl restart hacklab-ops.service
rm -rf "$TMP"
sleep 5
systemctl --no-pager --lines=5 status hacklab-ops.service || true
EOS
REMOTE
echo "installed; check with scripts/status.sh $device"
