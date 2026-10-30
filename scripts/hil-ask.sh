#!/usr/bin/env bash
# Hardware-in-the-loop test of the AI helper. Run ON the Pi as root with a box
# attached and ANTHROPIC_API_KEY in the environment. Seeds a temp data dir with
# the stock sketch and the genie skeleton, starts the real app, asks, waits,
# prints the kid message, prompts and serial banner, then undoes.
# Usage: ANTHROPIC_API_KEY=... scripts/hil-ask.sh <box-id> <stock-sketch-dir> <skeleton.ino> "<request>"
set -euo pipefail
box=${1:?}; stock=${2:?}; skeleton=${3:?}; request=${4:?usage: hil-ask.sh <box> <stock-dir> <skeleton.ino> "<request>"}
: "${ANTHROPIC_API_KEY:?set ANTHROPIC_API_KEY}"
prefix=${PREFIX:-/opt/hacklab}
port=${HIL_PORT:-8099}
data=$(mktemp -d /tmp/hacklab-ask-XXXX)
api="http://127.0.0.1:$port/api"
py="$prefix/venv/bin/python"

"$py" - "$data" "$box" "$stock" <<'PY'
import sys
from pathlib import Path
from hacklab.store import SketchStore
SketchStore(sys.argv[1]).ensure_baseline(sys.argv[2], Path(sys.argv[3]))
PY
mkdir -p "$data/boxes/$box/genie" && cp "$skeleton" "$data/boxes/$box/genie/skeleton.ino"

FAKE_BOARD=0 HACKLAB_DATA_DIR="$data" "$prefix/venv/bin/uvicorn" hacklab.app:app --host 127.0.0.1 --port "$port" --log-level warning &
app_pid=$!
trap 'kill $app_pid 2>/dev/null || true' EXIT
for _ in $(seq 300); do curl -fs "$api/status" >/dev/null 2>&1 && break; sleep 0.2; done  # Pi 3: the SDK import alone takes a while

json() { "$py" -c 'import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1], {"d": d}))' "$1"; }
wait_job() {
  local id=$1 t0; t0=$(date +%s)
  while :; do state=$(curl -fs "$api/jobs/$id" | json 'd["state"]'); case $state in done|failed) break;; esac; sleep 0.5; done
  echo "   job $state in $(( $(date +%s) - t0 )) s"
  echo "   kid: $(curl -fs "$api/jobs/$id" | json 'd["message_kid"]')"
  echo "   prompts: $(curl -fs "$api/jobs/$id" | json 'd["prompts"]')"
  [ "$state" = "done" ] || { echo "   log:"; tail -30 "$data/$box/logs/"*.log; exit 1; }
}
banner() {
  "$py" - <<'PY' || true
import glob, time, serial
p = sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))[0]
s = serial.Serial(p, 115200, timeout=3); time.sleep(0.3)
print("   serial:", s.read(120).decode("ascii", "replace").strip().splitlines()[:2])
PY
}

echo "1. select $box"; curl -fs -X POST "$api/box" -H 'content-type: application/json' -d "{\"id\":\"$box\"}" >/dev/null
st=$(curl -fs "$api/status"); echo "   board_connected=$(echo "$st" | json 'd["board_connected"]') ai_available=$(echo "$st" | json 'd["ai_available"]')"
echo "2. ask: $request"
body=$("$py" -c 'import json,sys; print(json.dumps({"text": sys.argv[1]}))' "$request")
wait_job "$(curl -fs -X POST "$api/ask" -H 'content-type: application/json' -d "$body" | json 'd["job_id"]')"
echo "   version: $(curl -fs "$api/status" | json 'd["current_version"]')"; banner
echo "   fragments: $(cat "$data/$box/versions/"*/fragments.json 2>/dev/null | tail -c 600)"
echo "3. undo"; wait_job "$(curl -fs -X POST "$api/undo" | json 'd["job_id"]')"; banner
echo "spend this month: \$$(cat "$data"/spend/*.jsonl | "$py" -c 'import json,sys; print(round(sum(json.loads(l)["usd"] for l in sys.stdin if l.strip()),4))')"
echo "asks.jsonl:"; cat "$data/$box/logs/asks.jsonl"
echo "HIL ASK PASSED (data kept in $data)"
