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

if aws cloudformation describe-stacks --region "$region" --stack-name "$stack" >/dev/null 2>&1; then
  # Existing device: keep the certificate. A fresh CSR would REPLACE it, so reuse the stored value.
  if aws cloudformation update-stack --region "$region" --stack-name "$stack" \
       --template-body "file://$root/provisioning/iot-device.yaml" \
       --parameters ParameterKey=DeviceName,UsePreviousValue=true \
                    ParameterKey=CertificateSigningRequest,UsePreviousValue=true >/dev/null 2>"$out/update.err"; then
    aws cloudformation wait stack-update-complete --region "$region" --stack-name "$stack"
  else
    if grep -q "No updates are to be performed" "$out/update.err"; then echo "stack unchanged"; else cat "$out/update.err" >&2; exit 1; fi
  fi
  rm -f "$out/update.err"
else
  aws cloudformation deploy --region "$region" --stack-name "$stack" \
    --template-file "$root/provisioning/iot-device.yaml" \
    --parameter-overrides "file://$out/params.json" --no-fail-on-empty-changeset
fi

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
