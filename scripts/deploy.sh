#!/usr/bin/env bash
# Create an IoT Job for one device and wait for the result.
# Usage: scripts/deploy.sh <device> <version>          deploy a release
#        scripts/deploy.sh <device> --op <rollback|restart|upload-logs|report-state|apt-upgrade>
set -euo pipefail
device=${1:?usage: deploy.sh <device> <version> | --op <op>}
shift
if [ "${1:-}" = "--op" ]; then op=${2:?}; doc="{\"op\":\"$op\"}"; label=$op
else version=${1:?usage: deploy.sh <device> <version>}; op=deploy; doc="{\"op\":\"deploy\",\"version\":\"$version\"}"; label="deploy-$version"; fi
region=${HACKLAB_AWS_REGION:-eu-west-1}
export AWS_PROFILE=${AWS_PROFILE:-busyweb-sso}
thing="hacklab-$device"
acct=$(aws sts get-caller-identity --query Account --output text)
job="hacklab-$device-$label-$(date -u +%Y%m%dT%H%M%S)"
job=${job//[^A-Za-z0-9_-]/-}
aws iot create-job --region "$region" --job-id "$job" \
  --targets "arn:aws:iot:$region:$acct:thing/$thing" \
  --document "$doc" --target-selection SNAPSHOT \
  --timeout-config inProgressTimeoutInMinutes=30 >/dev/null
echo "job $job created for $thing: $doc"
for _ in $(seq 240); do   # up to 20 min (the Pi may be off)
  st=$(aws iot describe-job-execution --region "$region" --job-id "$job" --thing-name "$thing" \
        --query 'execution.[status,statusDetails.detailsMap]' --output json 2>/dev/null || echo '["QUEUED",null]')
  status=$(echo "$st" | python3 -c 'import json,sys; print(json.load(sys.stdin)[0])')
  case $status in SUCCEEDED|FAILED|REJECTED|TIMED_OUT|CANCELED|REMOVED) break;; esac
  sleep 5
done
echo "$status"
echo "$st" | python3 -c 'import json,sys; d=json.load(sys.stdin)[1] or {}; [print(f"  {k}: {v}") for k,v in d.items()]'
[ "$status" = SUCCEEDED ]
