#!/usr/bin/env bash
# Usage: scripts/logs.sh <device>   -> IoT Job upload-logs, then download the bundle
set -euo pipefail
device=${1:?usage: logs.sh <device>}
root=$(cd "$(dirname "$0")/.." && pwd)
region=${HACKLAB_AWS_REGION:-eu-west-1}
export AWS_PROFILE=${AWS_PROFILE:-busyweb-trusted}
out="$root/provisioning/local/$device/logs"; mkdir -p "$out"
result=$("$root/scripts/deploy.sh" "$device" --op upload-logs) || { echo "$result"; exit 1; }
key=$(echo "$result" | sed -n 's/^  key: //p' | tail -1)
bucket=$(aws cloudformation describe-stacks --region "$region" --stack-name hacklab-releases \
  --query "Stacks[0].Outputs[?OutputKey=='BucketName'].OutputValue" --output text)
aws s3 cp --region "$region" --only-show-errors "s3://$bucket/$key" "$out/"
echo "downloaded $out/$(basename "$key")"; tar -tzf "$out/$(basename "$key")" | head
