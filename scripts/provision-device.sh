#!/usr/bin/env bash
# One-time per Pi: key + CSR locally, CloudFormation stack (thing, cert,
# policy), then cert/endpoint/root CA into provisioning/local/<device>/
# (git-ignored). Idempotent: re-running updates the stack and refreshes files.
# Usage: scripts/provision-device.sh <device>      e.g. pi3
set -euo pipefail
device=${1:?usage: provision-device.sh <device>}
region=${HACKLAB_AWS_REGION:-eu-west-1}   # IoT Core is not offered in af-south-1
export AWS_PROFILE=${AWS_PROFILE:-busyweb-sso}
root=$(cd "$(dirname "$0")/.." && pwd)
out="$root/provisioning/local/$device"
stack="hacklab-device-$device"
mkdir -p "$out"

if [ ! -f "$out/private.key" ]; then
  openssl ecparam -genkey -name prime256v1 -noout -out "$out/private.key"
  chmod 600 "$out/private.key"
fi
openssl req -new -key "$out/private.key" -subj "/CN=hacklab-$device" -out "$out/device.csr"

python3 - "$device" "$out/device.csr" > "$out/params.json" <<'PY'
import json, sys
print(json.dumps([
    {"ParameterKey": "DeviceName", "ParameterValue": sys.argv[1]},
    {"ParameterKey": "CertificateSigningRequest", "ParameterValue": open(sys.argv[2]).read()},
]))
PY

aws cloudformation deploy --region "$region" --stack-name "$stack" \
  --template-file "$root/provisioning/iot-device.yaml" \
  --parameter-overrides "file://$out/params.json" --no-fail-on-empty-changeset

cert_id=$(aws cloudformation describe-stacks --region "$region" --stack-name "$stack" \
  --query "Stacks[0].Outputs[?OutputKey=='CertificateId'].OutputValue" --output text)
aws iot describe-certificate --region "$region" --certificate-id "$cert_id" \
  --query certificateDescription.certificatePem --output text > "$out/cert.pem"
aws iot describe-endpoint --region "$region" --endpoint-type iot:Data-ATS \
  --query endpointAddress --output text > "$out/endpoint.txt"
curl -fsSL https://www.amazontrust.com/repository/AmazonRootCA1.pem -o "$out/AmazonRootCA1.pem"
rm -f "$out/params.json"

"$root/scripts/device-secrets.sh" backup "$device"   # Parameter Store copy: the only backup of the key
echo "thing hacklab-$device provisioned in $region; files in $out:"
ls -1 "$out"
echo "next: provisioning/install-ops.sh (copies $out to the Pi)"
