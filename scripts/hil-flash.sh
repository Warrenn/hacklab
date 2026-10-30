#!/usr/bin/env bash
# Hardware-in-the-loop smoke test for the flash core. Run ON the Pi as root
# with a Nano-class box attached. Drives the real app (FAKE_BOARD=0) through
# its HTTP API: select box -> flash a tiny serial sketch -> undo (flashes the
# stock sketch back) -> flash again -> reset. Prints timings and the serial
# banner after each step. Leaves the box on its stock sketch.
#
# Usage: scripts/hil-flash.sh <box-id> <stock-sketch-dir>
#   e.g. scripts/hil-flash.sh omnibot-forklift /root/hil/StockCode
set -euo pipefail
box=${1:?usage: hil-flash.sh <box-id> <stock-sketch-dir>}
stock=${2:?usage: hil-flash.sh <box-id> <stock-sketch-dir>}
prefix=${PREFIX:-/opt/hacklab}
port=${HIL_PORT:-8099}
data=$(mktemp -d /tmp/hacklab-hil-XXXX)
api="http://127.0.0.1:$port/api"

"$prefix/venv/bin/python" - "$data" "$box" "$stock" <<'PY'
import sys
from pathlib import Path
from hacklab.store import SketchStore
SketchStore(sys.argv[1]).ensure_baseline(sys.argv[2], Path(sys.argv[3]))
print("baseline seeded from", sys.argv[3])
PY

FAKE_BOARD=0 HACKLAB_DATA_DIR="$data" "$prefix/venv/bin/uvicorn" hacklab.app:app \
  --host 127.0.0.1 --port "$port" --log-level warning &
app_pid=$!
trap 'kill $app_pid 2>/dev/null || true' EXIT
for _ in $(seq 50); do curl -fs "$api/status" >/dev/null 2>&1 && break; sleep 0.2; done

json() { "$prefix/venv/bin/python" -c 'import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1], {"d": d}))' "$1"; }
wait_job() {  # prints final state, fails the script if not done
  local id=$1 t0; t0=$(date +%s)
  while :; do
    state=$(curl -fs "$api/jobs/$id" | json 'd["state"]')
    case $state in done|failed) break;; esac; sleep 0.5
  done
  echo "   job $state in $(( $(date +%s) - t0 )) s: $(curl -fs "$api/jobs/$id" | json 'd["message_kid"]')"
  [ "$state" = "done" ] || { echo "   log: $data/$box/logs/$(curl -fs "$api/jobs/$id" | json 'd["log_ref"]')"; cat "$data/$box/logs/"*.log | tail -20; exit 1; }
}
banner() {  # opening the port resets the Nano; read its first lines
  "$prefix/venv/bin/python" - <<'PY' || true
import glob, time, serial
p = sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))[0]
s = serial.Serial(p, 115200, timeout=3); time.sleep(0.3)
print("   serial:", s.read(80).decode("ascii", "replace").strip().splitlines()[:1])
PY
}

echo "1. select box $box"; curl -fs -X POST "$api/box" -H 'content-type: application/json' -d "{\"id\":\"$box\"}" >/dev/null
st=$(curl -fs "$api/status"); echo "   board_connected=$(echo "$st" | json 'd["board_connected"]') current=$(echo "$st" | json 'd["current_version"]')"
[ "$(echo "$st" | json 'd["board_connected"]')" = True ] || { echo "no board detected"; exit 1; }

hil='void setup(){Serial.begin(115200);} void loop(){Serial.println("hacklab hil"); delay(1000);}'
echo "2. flash HIL sketch"; wait_job "$(curl -fs -X POST "$api/flash/sketch" -H 'content-type: application/json' -d "{\"source\":$(printf '%s' "$hil" | "$prefix/venv/bin/python" -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}" | json 'd["job_id"]')"; banner
echo "3. undo (back to stock)"; wait_job "$(curl -fs -X POST "$api/undo" | json 'd["job_id"]')"; banner
echo "4. flash HIL sketch again"; wait_job "$(curl -fs -X POST "$api/flash/sketch" -H 'content-type: application/json' -d "{\"source\":$(printf '%s' "$hil" | "$prefix/venv/bin/python" -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}" | json 'd["job_id"]')"
echo "5. reset (back to how it came)"; wait_job "$(curl -fs -X POST "$api/reset" | json 'd["job_id"]')"; banner
st=$(curl -fs "$api/status"); echo "   current=$(echo "$st" | json 'd["current_version"]') versions=$(echo "$st" | json 'd["versions_count"]')"
echo "bootloader cached for $box: $(cat "$data/$box/board.json")"
echo "HIL PASSED (data kept in $data)"
