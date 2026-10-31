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
run apt-get install -y -qq git python3-venv logrotate avahi-daemon curl minisign unattended-upgrades
# P7b: security updates install themselves (no automatic reboot); rpcbind serves nothing here.
run bash -c 'printf "%s\n" "APT::Periodic::Update-Package-Lists \"1\";" "APT::Periodic::Unattended-Upgrade \"1\";" > /etc/apt/apt.conf.d/20auto-upgrades'
run systemctl enable --now unattended-upgrades
run systemctl disable --now rpcbind.socket rpcbind.service 2>/dev/null || true
# P7b (owner-approved 2026-10-31): keys only on the LAN sshd (Tailscale SSH is the remote path),
# and the imager's passwordless sudo for the login user becomes password-required.
run bash -c 'printf "%s\n" "PasswordAuthentication no" "KbdInteractiveAuthentication no" "PermitRootLogin prohibit-password" > /etc/ssh/sshd_config.d/10-hacklab.conf'
run bash -c 'sshd -t && systemctl reload ssh'
# P7b: input firewall (see provisioning/nftables.conf). Enabled only after the hotspot
# fallback was tested with it on 2026-10-31.
run install -m 644 "$REPO_DIR/provisioning/nftables.conf" /etc/nftables.conf
run install -d /etc/systemd/system/nftables.service.d
run install -m 644 "$REPO_DIR/provisioning/systemd/nftables.service.d-hacklab.conf" /etc/systemd/system/nftables.service.d/hacklab.conf
run systemctl daemon-reload
run bash -c 'nft -c -f /etc/nftables.conf && systemctl enable --now nftables'
for f in /etc/sudoers.d/*-nopasswd; do
  [ -f "$f" ] || continue
  run bash -c "sed 's/NOPASSWD: //' '$f' > '${f%-nopasswd}-passwd' && visudo -cf '${f%-nopasswd}-passwd' && rm -f '$f'"
done

log "2/9 toolchain + venv (provisioning/install-toolchain.sh)"
run env PREFIX="$PREFIX" REPO_DIR="$SRC" "$SRC/provisioning/install-toolchain.sh"

log "3/9 users, directories, current -> src"
if ! id -u hacklab >/dev/null 2>&1; then
  run useradd --system --home "$PREFIX" --shell /usr/sbin/nologin --groups dialout hacklab
fi
if ! id -u hacklab-ops >/dev/null 2>&1; then
  run useradd --system --home "$PREFIX/ops" --shell /usr/sbin/nologin hacklab-ops
fi
run mkdir -p "$PREFIX/data/boxes" "$PREFIX/data/work" /etc/hacklab
run chown -R hacklab:hacklab "$PREFIX/data" "$PREFIX/arduino"
run ln -sfn "$SRC" "$PREFIX/current"

log "4/9 config + env file (key never in git)"
[ -f /etc/hacklab/config.toml ] || run install -m 644 "$SRC/provisioning/appliance.toml" /etc/hacklab/config.toml
# /etc/default/hacklab: merge (never clobber a key someone pushed); root-only.
setvar() {  # setvar NAME VALUE -> replace or append NAME=VALUE
  [ "$DRY" = 1 ] && { printf '  would: set %s in /etc/default/hacklab\n' "$1"; return; }
  { grep -v "^$1=" /etc/default/hacklab 2>/dev/null || true; printf '%s=%s\n' "$1" "$2"; } > /etc/default/hacklab.tmp
  install -m 600 /etc/default/hacklab.tmp /etc/default/hacklab && rm -f /etc/default/hacklab.tmp
}
[ -f /etc/default/hacklab ] || run install -m 600 /dev/null /etc/default/hacklab
setvar HACKLAB_CONFIG /etc/hacklab/config.toml
setvar HACKLAB_DATA_DIR "$PREFIX/data"
setvar HACKLAB_BOXES_DIR "$PREFIX/current/boxes"
if [ -n "${HACKLAB_API_KEY:-}" ]; then setvar ANTHROPIC_API_KEY "$HACKLAB_API_KEY"
elif ! grep -q '^ANTHROPIC_API_KEY=' /etc/default/hacklab 2>/dev/null; then setvar ANTHROPIC_API_KEY ""; fi

log "5/9 systemd unit, logrotate, journald limit"
run install -m 644 "$SRC/provisioning/hacklab-app.service" /etc/systemd/system/hacklab-app.service
run install -m 644 "$SRC/provisioning/hacklab.logrotate" /etc/logrotate.d/hacklab
run mkdir -p /etc/systemd/journald.conf.d /var/log/journal
run install -m 644 "$SRC/provisioning/systemd/journald-hacklab.conf" /etc/systemd/journald.conf.d/hacklab.conf
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

log "6b/9 signed updates: public key, apply helper, sudoers, releases dir"
run install -m 644 "$SRC/provisioning/minisign.pub" "$PREFIX/minisign.pub"
run install -m 755 "$SRC/provisioning/hacklab-apply" "$PREFIX/bin/hacklab-apply"
run install -m 440 "$SRC/provisioning/hacklab-ops.sudoers" /etc/sudoers.d/hacklab-ops
run install -d -o hacklab-ops -g hacklab-ops -m 755 "$PREFIX/releases"
if [ -f /etc/default/hacklab-ops ] && [ "$DRY" = 0 ]; then   # agent settings for jobs (option B credentials)
  for kv in "HACKLAB_ROLE_ALIAS=hacklab-device" "HACKLAB_BUCKET=${HACKLAB_BUCKET:-}" "HACKLAB_CRED_ENDPOINT=${HACKLAB_CRED_ENDPOINT:-}"; do
    k=${kv%%=*}; v=${kv#*=}; [ -n "$v" ] || continue
    { grep -v "^$k=" /etc/default/hacklab-ops || true; printf '%s=%s\n' "$k" "$v"; } > /etc/default/hacklab-ops.tmp
    mv /etc/default/hacklab-ops.tmp /etc/default/hacklab-ops
  done
fi

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
