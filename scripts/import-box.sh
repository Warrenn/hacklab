#!/usr/bin/env bash
# Import a Hack Pack box from the IDE into a box profile.
#   scripts/import-box.sh <ide-slug> [--fqbn arduino:avr:nano] [--name "Pretty Name"]
# 1. pw scripts/import-box.js  -> dump of the editor files (machine-wide Playwright harness)
# 2. hacklab.importer           -> boxes/<id>/ (MIT stock committed) or provisioning/local/boxes/<id>/ (staged)
# 3. load_box                   -> the profile validates
# Then: fill hardware.md / concepts.toml, add behaviours, scripts/check-box.sh <id>.
set -euo pipefail
slug=${1:?usage: import-box.sh <ide-slug> [--fqbn ...] [--name ...]}
shift
root=$(cd "$(dirname "$0")/.." && pwd)
py=${HACKLAB_PYTHON:-$root/.venv/bin/python}; [ -x "$py" ] || py=python3
dump="$root/provisioning/local/ide/$slug.json"
mkdir -p "$(dirname "$dump")"
pw "$root/scripts/import-box.js" "$slug" "$dump"
"$py" -m hacklab.importer "$dump" "$@"
"$py" -c 'import sys; from pathlib import Path; from hacklab.profiles import load_box; b = load_box(Path(sys.argv[1])); print(f"profile ok: {b.name} ({b.stock_location} stock, fqbn {b.fqbn})")' "$root/boxes/$slug"
echo "next: edit boxes/$slug/hardware.md and concepts.toml, add behaviours, run scripts/check-box.sh $slug"
