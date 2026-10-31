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
#        scripts/device-secrets.sh backup-signing-key        ~/.minisign/hacklab.key (passphrase-encrypted) -> /hacklab/minisign/secret-key
#        scripts/device-secrets.sh restore-signing-key       parameter -> ~/.minisign/hacklab.key (mode 600)
set -euo pipefail
cmd=${1:?usage: device-secrets.sh backup|restore|list <device> [dir] | backup-key|restore-key [env-file]}
case $cmd in backup-key|restore-key|backup-signing-key|restore-signing-key) device=${2:-};; *) device=${2:?usage: device-secrets.sh backup|restore|list <device> [dir]};; esac
region=${HACKLAB_AWS_REGION:-eu-west-1}
export AWS_PROFILE=${AWS_PROFILE:-busyweb-trusted}
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
  backup-signing-key)
    keyfile=${2:-$HOME/.minisign/hacklab.key}
    # kdf field "Sc" = passphrase-protected. Owner's decision 2026-10-30: the key is kept WITHOUT a
    # passphrase so releases can be signed unattended; warn, since AWS access + this backup can sign.
    if ! python3 -c 'import base64,sys; raw=base64.b64decode(open(sys.argv[1]).read().splitlines()[1]); sys.exit(0 if raw[0:2]==b"Ed" and raw[2:4]==b"Sc" else 1)' "$keyfile"; then
      echo "warning: $keyfile has no passphrase; anyone who can read /hacklab/minisign/secret-key can sign releases" >&2
    fi
    # the file is already passphrase-encrypted by minisign; SecureString adds the AWS layer on top
    aws ssm put-parameter --region "$region" --name /hacklab/minisign/secret-key --type SecureString \
      --value "file://$keyfile" --overwrite --tier Standard >/dev/null
    echo "backed up $keyfile -> /hacklab/minisign/secret-key" ;;
  restore-signing-key)
    keyfile=${2:-$HOME/.minisign/hacklab.key}
    mkdir -p "$(dirname "$keyfile")" && chmod 700 "$(dirname "$keyfile")"
    aws ssm get-parameter --region "$region" --name /hacklab/minisign/secret-key --with-decryption --output json \
      | python3 -c 'import json,sys; sys.stdout.write(json.load(sys.stdin)["Parameter"]["Value"])' > "$keyfile.tmp"
    mv "$keyfile.tmp" "$keyfile" && chmod 600 "$keyfile"
    echo "restored $keyfile (you will be asked for the passphrase when signing)" ;;
  *) echo "unknown command $cmd" >&2; exit 1 ;;
esac
