#!/usr/bin/env bash
# Validate one box profile and compile every behaviour, template and repo stock
# sketch. Usage: scripts/check-box.sh <id>
# Toolchain: HACKLAB_CLI (+ HACKLAB_CLI_CONFIG) if set; else /opt/hacklab (the Pi
# or the dev container); else Docker (hacklab-dev image, built from Dockerfile.dev).
set -euo pipefail
id=${1:?usage: check-box.sh <id>}
root=$(cd "$(dirname "$0")/.." && pwd)
py=${HACKLAB_PYTHON:-$root/.venv/bin/python}; [ -x "$py" ] || py=python3

if [ -z "${HACKLAB_CLI:-}" ] && [ -x /opt/hacklab/bin/arduino-cli ]; then
  export HACKLAB_CLI=/opt/hacklab/bin/arduino-cli HACKLAB_CLI_CONFIG=/opt/hacklab/arduino/arduino-cli.yaml
fi
if [ -z "${HACKLAB_CLI:-}" ]; then
  echo "[check-box] no local toolchain; running inside the hacklab-dev container"
  docker image inspect hacklab-dev >/dev/null 2>&1 || docker build -q -f "$root/Dockerfile.dev" -t hacklab-dev "$root" >/dev/null
  exec docker run --rm -v "$root:/app" -w /app -e HACKLAB_CLI=/opt/hacklab/bin/arduino-cli \
    -e HACKLAB_CLI_CONFIG=/opt/hacklab/arduino/arduino-cli.yaml hacklab-dev scripts/check-box.sh "$id"
fi

echo "[check-box] validating profile $id"
"$py" - "$root" "$id" <<'PY'
import re, sys
from pathlib import Path
from hacklab.profiles import load_box
box = load_box(Path(sys.argv[1]) / "boxes" / sys.argv[2])
bad = []
for item in list(box.behaviours.values()) + list(box.templates.values()):
    for text in (item.title, item.description):
        if re.search(r"https?://|www\.", text): bad.append(f"{item.id}: link in copy")
        if re.search(r"[\U0001F300-\U0001FAFF☀-➿]", text): bad.append(f"{item.id}: emoji in copy")
        if re.search(r"\bAI\b(?! helper)", text): bad.append(f"{item.id}: say 'the AI helper'")
for cid, c in box.concepts.items():
    if re.search(r"https?://|www\.", c.explanation): bad.append(f"concept {cid}: link")
if bad: sys.exit("\n".join(bad))
n = len(box.behaviours) + len(box.templates)
print(f"ok: {len(box.behaviours)} behaviours, {len(box.templates)} templates, {len(box.concepts)} concepts, {n} sketches to compile")
PY
echo "[check-box] compiling"
HACKLAB_BOX="$id" "$py" -m pytest -q "$root/tests/test_boxes_compile.py" -k "$id" -p no:cacheprovider
