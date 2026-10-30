#!/usr/bin/env bash
# Build, sign and upload a release. Usage: scripts/release.sh [version]
#   version defaults to the current git tag (v1.2.3 -> 1.2.3); any string for test builds.
# Env: MINISIGN_KEY (default ~/.minisign/hacklab.key, passphrase prompt), RELEASE_OUT (dir),
#      RELEASE_NO_UPLOAD=1 (build + sign only), HACKLAB_AWS_REGION, AWS_PROFILE.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
version=${1:-$(git -C "$root" describe --tags --exact-match 2>/dev/null | sed 's/^v//' || true)}
[ -n "$version" ] || { echo "no version: tag the commit (vX.Y.Z) or pass one" >&2; exit 1; }
[[ $version =~ ^[0-9A-Za-z][0-9A-Za-z.+-]{0,63}$ ]] || { echo "bad version $version" >&2; exit 1; }
key=${MINISIGN_KEY:-$HOME/.minisign/hacklab.key}
[ -f "$key" ] || { echo "signing key not found: $key (scripts/device-secrets.sh restore-signing-key)" >&2; exit 1; }
out=${RELEASE_OUT:-$root/dist}; mkdir -p "$out"
region=${HACKLAB_AWS_REGION:-eu-west-1}
export AWS_PROFILE=${AWS_PROFILE:-busyweb-sso}
name="hacklab-$version.tar.gz"
work=$(mktemp -d); trap 'rm -rf "$work"' EXIT

# 1. the tree: committed files only (never .env, provisioning/local, screenshots)
git -C "$root" archive --format=tar HEAD hacklab boxes static provisioning scripts ops pyproject.toml README.md LICENSE \
  | tar -x -C "$work"
rm -rf "$work/tests" "$work/provisioning/local"
# 2. manifest with per-file hashes
python3 - "$work" "$version" "$(git -C "$root" rev-parse HEAD)" <<'PY'
import hashlib, json, sys, time
from pathlib import Path
root = Path(sys.argv[1]); files = sorted(p for p in root.rglob("*") if p.is_file())
m = {"version": sys.argv[2], "git": sys.argv[3], "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
     "sha256": {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
(root / "manifest.json").write_text(json.dumps(m, indent=1, sort_keys=True))
PY
# 3. tarball + signature
# member names without a leading ./ ; no macOS xattrs/resource forks in the archive
(cd "$work" && COPYFILE_DISABLE=1 tar --no-xattrs -czf "$out/$name" -- *)
minisign -S -s "$key" -m "$out/$name" -t "hacklab $version $(date -u +%Y-%m-%dT%H:%M:%SZ)" >/dev/null
minisign -V -q -p "$root/provisioning/minisign.pub" -m "$out/$name" 2>/dev/null || \
  minisign -V -q -p "$(dirname "$key")/../$(basename "$key" .key).pub" -m "$out/$name" 2>/dev/null || true
echo "built $out/$name ($(du -h "$out/$name" | cut -f1)) + .minisig"
[ "${RELEASE_NO_UPLOAD:-0}" = 1 ] && exit 0
# 4. upload
bucket=$(aws cloudformation describe-stacks --region "$region" --stack-name hacklab-releases \
  --query "Stacks[0].Outputs[?OutputKey=='BucketName'].OutputValue" --output text)
aws s3 cp --region "$region" --only-show-errors "$out/$name" "s3://$bucket/releases/$version/$name"
aws s3 cp --region "$region" --only-show-errors "$out/$name.minisig" "s3://$bucket/releases/$version/$name.minisig"
echo "uploaded to s3://$bucket/releases/$version/  -> scripts/deploy.sh <device> $version"
