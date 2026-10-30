#!/usr/bin/env bash
# Back up / restore a device's provisioning files (IoT cert, private key, CSR,
# endpoint, root CA) as SecureString parameters in AWS Systems Manager
# Parameter Store, path /hacklab/devices/<device>/<file>. Standard tier (free,
# <= 4 KB each), encrypted with the account's default SSM KMS key.
#
# Usage: scripts/device-secrets.sh backup <device>
#        scripts/device-secrets.sh restore <device> [dir]   (default provisioning/local/<device>)
#        scripts/device-secrets.sh list <device>
#        scripts/device-secrets.sh backup-key [env-file]     ANTHROPIC_API_KEY from .env -> /hacklab/anthropic/api-key
#        scripts/device-secrets.sh restore-key [env-file]    parameter -> ANTHROPIC_API_KEY line in .env
set -euo pipefail
cmd=${1:?usage: device-secrets.sh backup|restore|list <device> [dir] | backup-key|restore-key [env-file]}
case $cmd in backup-key|restore-key) device=${2:-};; *) device=${2:?usage: device-secrets.sh backup|restore|list <device> [dir]};; esac
region=${HACKLAB_AWS_REGION:-eu-west-1}
export AWS_PROFILE=${AWS_PROFILE:-busyweb-sso}
root=$(cd "$(dirname "$0")/.." && pwd)
dir=${3:-$root/provisioning/local/$device}
prefix="/hacklab/devices/$device"
files="cert.pem private.key device.csr endpoint.txt AmazonRootCA1.pem"

case $cmd in
  backup)
    for f in $files; do
      [ -f "$dir/$f" ] || { echo "skip $f (not present)"; continue; }
      [ "$(wc -c < "$dir/$f")" -le 4096 ] || { echo "$f exceeds the 4 KB standard-tier limit" >&2; exit 1; }
      aws ssm put-parameter --region "$region" --name "$prefix/$f" --type SecureString \
        --value "file://$dir/$f" --overwrite --tier Standard >/dev/null
      echo "backed up $f -> $prefix/$f"
    done ;;
  restore)
    mkdir -p "$dir"
    for f in $files; do
      # json + python so the value is written byte-for-byte (text output appends a newline)
      if aws ssm get-parameter --region "$region" --name "$prefix/$f" --with-decryption --output json 2>/dev/null \
           | python3 -c 'import json,sys; sys.stdout.write(json.load(sys.stdin)["Parameter"]["Value"])' > "$dir/$f.tmp" \
           && [ -s "$dir/$f.tmp" ]; then
        mv "$dir/$f.tmp" "$dir/$f"; echo "restored $f"
      else
        rm -f "$dir/$f.tmp"; echo "skip $f (no parameter)"
      fi
    done
    chmod 600 "$dir/private.key" 2>/dev/null || true ;;
  list)
    aws ssm get-parameters-by-path --region "$region" --path "$prefix" \
      --query 'Parameters[].[Name,Type,LastModifiedDate]' --output table ;;
  backup-key)
    envfile=${2:-$root/.env}
    key=$(grep -E '^ANTHROPIC_API_KEY=' "$envfile" | head -1 | cut -d= -f2-)
    [ -n "$key" ] || { echo "no ANTHROPIC_API_KEY in $envfile" >&2; exit 1; }
    aws ssm put-parameter --region "$region" --name /hacklab/anthropic/api-key --type SecureString \
      --value "$key" --overwrite --tier Standard >/dev/null
    echo "backed up ANTHROPIC_API_KEY -> /hacklab/anthropic/api-key" ;;
  restore-key)
    envfile=${2:-$root/.env}
    key=$(aws ssm get-parameter --region "$region" --name /hacklab/anthropic/api-key --with-decryption --output json \
      | python3 -c 'import json,sys; sys.stdout.write(json.load(sys.stdin)["Parameter"]["Value"])')
    touch "$envfile"; chmod 600 "$envfile"
    grep -vE '^ANTHROPIC_API_KEY=' "$envfile" > "$envfile.tmp" || true
    printf 'ANTHROPIC_API_KEY=%s\n' "$key" >> "$envfile.tmp" && mv "$envfile.tmp" "$envfile"
    echo "restored ANTHROPIC_API_KEY into $envfile" ;;
  *) echo "unknown command $cmd" >&2; exit 1 ;;
esac
