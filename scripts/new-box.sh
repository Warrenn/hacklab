#!/usr/bin/env bash
# Scaffold boxes/<id>/ from boxes/_template. Usage: scripts/new-box.sh <id> "<Name>"
set -euo pipefail
id=${1:?usage: new-box.sh <id> "<Name>"}; name=${2:?usage: new-box.sh <id> "<Name>"}
[[ $id =~ ^[a-z0-9-]+$ ]] || { echo "id must be lower-case letters, digits and dashes" >&2; exit 1; }
root=$(cd "$(dirname "$0")/.." && pwd)
dest="$root/boxes/$id"
[ -e "$dest" ] && { echo "$dest already exists" >&2; exit 1; }
cp -R "$root/boxes/_template" "$dest"
for f in "$dest"/profile.toml "$dest"/hardware.md; do
  sed -i.bak "s/BOX_ID/$id/g; s/BOX_NAME/$name/g" "$f" && rm -f "$f.bak"
done
mkdir -p "$dest/behaviours" "$dest/templates" "$dest/stock"
echo "created $dest -- fill in pins.toml, hardware.md, concepts.toml, then scripts/check-box.sh $id"
