#!/usr/bin/env bash
# Push ANTHROPIC_API_KEY from the git-ignored .env into /etc/default/hacklab on
# the Pi (root-only) over Tailscale, then restart the app. Never via git.
# Usage: scripts/push-key.sh [ssh-target]   (default root@hacklab)
set -euo pipefail
target=${1:-root@hacklab}
root=$(cd "$(dirname "$0")/.." && pwd)
key=$(grep -E '^ANTHROPIC_API_KEY=' "$root/.env" | head -1 | cut -d= -f2-)
[ -n "$key" ] || { echo "no ANTHROPIC_API_KEY in $root/.env" >&2; exit 1; }
printf '%s\n' "$key" | ssh "$target" 'read -r key; f=/etc/default/hacklab; touch "$f"; chmod 600 "$f";
  { grep -v "^ANTHROPIC_API_KEY=" "$f" || true; printf "ANTHROPIC_API_KEY=%s\n" "$key"; } > "$f.tmp" && mv "$f.tmp" "$f" && chmod 600 "$f";
  systemctl restart hacklab-app.service; echo "key installed, app restarted"'
