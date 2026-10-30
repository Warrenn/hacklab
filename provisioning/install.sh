#!/usr/bin/env bash
# Turn a Raspberry Pi into the Hack Lab appliance. Idempotent; run as root
# from a clone of the repo (default /opt/hacklab/src):
#   sudo provisioning/install.sh            # or: sudo HACKLAB_API_KEY=sk-... provisioning/install.sh
#   provisioning/install.sh --dry-run       # print what would be done (no root needed)
# After the first run: scripts/push-key.sh (API key) and provisioning/install-ops.sh
# (IoT agent) from the maintainer's machine.
set -euo pipefail
PREFIX=${PREFIX:-/opt/hacklab}
SRC=${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1
log() { printf '[install] %s\n' "$*"; }
run() { if [ "$DRY" = 1 ]; then printf '  would: %s\n' "$*"; else "$@"; fi; }
if [ "$DRY" = 0 ] && [ "$(id -u)" != 0 ]; then echo "run as root (or --dry-run)" >&2; exit 1; fi

log "1/9 apt packages"
run apt-get install -y -qq git python3-venv logrotate avahi-daemon curl

log "2/9 toolchain + venv (provisioning/install-toolchain.sh)"
run env PREFIX="$PREFIX" REPO_DIR="$SRC" "$SRC/provisioning/install-toolchain.sh"

log "3/9 users, directories, current -> src"
if ! id -u hacklab >/dev/null 2>&1; then
  run useradd --system --home "$PREFIX" --shell /usr/sbin/nologin --groups dialout hacklab
fi
run mkdir -p "$PREFIX/data/boxes" "$PREFIX/data/work" /etc/hacklab
run chown -R hacklab:hacklab "$PREFIX/data" "$PREFIX/arduino"
run ln -sfn "$SRC" "$PREFIX/current"

log "4/9 config + env file (key never in git)"
[ -f /etc/hacklab/config.toml ] || run install -m 644 "$SRC/provisioning/appliance.toml" /etc/hacklab/config.toml
if [ ! -f /etc/default/hacklab ]; then
  run install -m 600 /dev/null /etc/default/hacklab
  if [ "$DRY" = 0 ]; then
    printf 'HACKLAB_CONFIG=/etc/hacklab/config.toml\nHACKLAB_DATA_DIR=%s/data\nHACKLAB_BOXES_DIR=%s/current/boxes\nANTHROPIC_API_KEY=%s\n' \
      "$PREFIX" "$PREFIX" "${HACKLAB_API_KEY:-}" > /etc/default/hacklab
  fi
elif [ -n "${HACKLAB_API_KEY:-}" ] && [ "$DRY" = 0 ]; then
  grep -v '^ANTHROPIC_API_KEY=' /etc/default/hacklab > /etc/default/hacklab.tmp || true
  printf 'ANTHROPIC_API_KEY=%s\n' "$HACKLAB_API_KEY" >> /etc/default/hacklab.tmp
  install -m 600 /etc/default/hacklab.tmp /etc/default/hacklab && rm -f /etc/default/hacklab.tmp
fi

log "5/9 systemd unit, logrotate, journald limit"
run install -m 644 "$SRC/provisioning/hacklab-app.service" /etc/systemd/system/hacklab-app.service
run install -m 644 "$SRC/provisioning/hacklab.logrotate" /etc/logrotate.d/hacklab
run mkdir -p /etc/systemd/journald.conf.d
[ -f /etc/systemd/journald.conf.d/hacklab.conf ] || run bash -c 'printf "[Journal]\nSystemMaxUse=200M\n" > /etc/systemd/journald.conf.d/hacklab.conf'
run systemctl daemon-reload
run systemctl restart systemd-journald

log "6/9 WiFi: NetworkManager PMF fix, comitup hands port 80 to hacklab-app"
run install -m 644 "$SRC/provisioning/10-wifi-no-pmf.conf" /etc/NetworkManager/conf.d/10-wifi-no-pmf.conf
if [ -f /etc/comitup.conf ] && ! grep -q '^web_service: hacklab-app.service' /etc/comitup.conf; then
  run sed -i 's/^web_service:.*$//' /etc/comitup.conf
  run bash -c 'printf "\nweb_service: hacklab-app.service\n" >> /etc/comitup.conf'
  run systemctl restart comitup
fi
run systemctl disable hacklab-app.service   # comitup owns enable/disable; start it now
run systemctl restart hacklab-app.service

log "7/9 ops agent (only if the device certs are already in place)"
if [ -f "$PREFIX/data/iot/cert.pem" ] && [ -f /etc/default/hacklab-ops ]; then
  run env HACKLAB_SRC="$SRC" bash "$SRC/provisioning/install-ops-local.sh" "$PREFIX/data/iot"
else
  log "   skipped: run provisioning/install-ops.sh <device> from the maintainer's machine"
fi

log "8/9 device-only content dirs (stock code / skeletons that are not in git)"
for b in "$SRC"/boxes/*/; do
  id=$(basename "$b"); [ "$id" = _template ] && continue
  run install -d -o hacklab -g hacklab "$PREFIX/data/boxes/$id/stock" "$PREFIX/data/boxes/$id/genie"
done

log "9/9 health"
if [ "$DRY" = 0 ]; then
  sleep 25   # the Anthropic SDK import alone takes ~15 s on a Pi 3
  for u in hacklab-app hacklab-ops comitup tailscaled avahi-daemon; do printf '   %-14s %s\n' "$u" "$(systemctl is-active "$u" 2>/dev/null || true)"; done
  printf '   /api/status    %s\n' "$(curl -fs http://127.0.0.1/api/status || echo unreachable)"
  grep -q '^ANTHROPIC_API_KEY=.\+' /etc/default/hacklab || log "   no API key yet: run scripts/push-key.sh from the maintainer's machine"
fi
log "done"
