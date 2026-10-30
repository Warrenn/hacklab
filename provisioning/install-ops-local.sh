#!/usr/bin/env bash
# Install/upgrade the ops agent ON the Pi (root). Expects the device files
# (cert.pem, private.key, AmazonRootCA1.pem) in $1 and the thing/endpoint in
# HACKLAB_THING / HACKLAB_IOT_ENDPOINT (or an existing /etc/default/hacklab-ops).
# Called by provisioning/install-ops.sh (from the maintainer's machine) and by
# provisioning/install.sh. Idempotent.
set -euo pipefail
files=${1:?usage: install-ops-local.sh <dir-with-cert.pem-private.key-AmazonRootCA1.pem>}
src=${HACKLAB_SRC:-/opt/hacklab/src}
agent_dir=${HACKLAB_AGENT_DIR:-$src/ops}   # where agent.py + requirements.txt are
id -u hacklab-ops >/dev/null 2>&1 || useradd --system --home /opt/hacklab/ops --shell /usr/sbin/nologin hacklab-ops
mkdir -p /opt/hacklab/ops /opt/hacklab/data/iot
install -m 644 "$agent_dir"/*.py "$agent_dir/requirements.txt" /opt/hacklab/ops/   # agent.py, jobs.py, awsio.py
if [ "$(realpath "$files")" != "$(realpath /opt/hacklab/data/iot)" ]; then
  for f in cert.pem private.key AmazonRootCA1.pem; do
    [ -f "$files/$f" ] && install -o hacklab-ops -g hacklab-ops -m 600 "$files/$f" /opt/hacklab/data/iot/
  done
fi
chown -R hacklab-ops:hacklab-ops /opt/hacklab/data/iot && chmod 600 /opt/hacklab/data/iot/*
[ -x /opt/hacklab/ops/venv/bin/python ] || python3 -m venv /opt/hacklab/ops/venv
/opt/hacklab/ops/venv/bin/pip install -q --disable-pip-version-check -r /opt/hacklab/ops/requirements.txt
if [ -n "${HACKLAB_THING:-}" ] && [ -n "${HACKLAB_IOT_ENDPOINT:-}" ]; then
  printf 'HACKLAB_THING=%s\nHACKLAB_IOT_ENDPOINT=%s\nHACKLAB_IOT_DIR=/opt/hacklab/data/iot\n' \
    "$HACKLAB_THING" "$HACKLAB_IOT_ENDPOINT" > /etc/default/hacklab-ops
fi
[ -f /etc/default/hacklab-ops ] || { echo "no /etc/default/hacklab-ops and no HACKLAB_THING/ENDPOINT given" >&2; exit 1; }
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
