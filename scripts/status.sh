#!/usr/bin/env bash
# Print the device shadow's reported state and how old it is.
# Usage: scripts/status.sh <device>      e.g. pi3
set -euo pipefail
device=${1:?usage: status.sh <device>}
region=${HACKLAB_AWS_REGION:-eu-west-1}
export AWS_PROFILE=${AWS_PROFILE:-busyweb-sso}
aws iot-data get-thing-shadow --region "$region" --thing-name "hacklab-$device" /dev/stdout \
  | python3 -c '
import json, sys, time
d = json.load(sys.stdin); r = d["state"].get("reported", {})
age = int(time.time()) - r.get("ts", 0)
print(f"hacklab-{sys.argv[1]}: heartbeat {age}s ago" if r.get("ts") else "no heartbeat yet")
for k, v in r.items(): print(f"  {k:14} {v}")
' "$device"
