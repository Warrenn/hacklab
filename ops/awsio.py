"""AWS access for the ops agent (P5c, option B): the device trades its IoT
certificate for short-lived role credentials through the IoT credentials
provider, then talks to S3 with boto3. Also the minisign verifier and the
sudo helper runner. Kept apart from jobs.py so the executor stays testable."""

from __future__ import annotations

import json
import ssl
import subprocess
import time
import urllib.request
from pathlib import Path


class IotCredentials:
    """Mutual TLS + x-amzn-iot-thingname -> temporary accessKeyId/secretAccessKey/sessionToken."""

    def __init__(self, endpoint: str, thing: str, role_alias: str, iot_dir: Path):
        self.url = f"https://{endpoint}/role-aliases/{role_alias}/credentials"
        self.thing = thing
        self.ctx = ssl.create_default_context(cafile=str(iot_dir / "AmazonRootCA1.pem"))
        self.ctx.load_cert_chain(str(iot_dir / "cert.pem"), str(iot_dir / "private.key"))
        self._creds: dict | None = None
        self._until = 0.0

    def get(self) -> dict:
        if self._creds and time.time() < self._until - 300:
            return self._creds
        req = urllib.request.Request(self.url, headers={"x-amzn-iot-thingname": self.thing})
        with urllib.request.urlopen(req, context=self.ctx, timeout=20) as r:
            c = json.load(r)["credentials"]
        self._creds = c
        self._until = (
            time.mktime(time.strptime(c["expiration"], "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
        )
        return c


class S3:
    def __init__(self, bucket: str, region: str, creds: IotCredentials):
        self.bucket, self.region, self.creds = bucket, region, creds

    def _client(self):
        import boto3  # in the ops venv only

        c = self.creds.get()
        return boto3.client(
            "s3",
            region_name=self.region,
            aws_access_key_id=c["accessKeyId"],
            aws_secret_access_key=c["secretAccessKey"],
            aws_session_token=c["sessionToken"],
        )

    def download(self, key: str, dest: Path) -> None:
        from botocore.exceptions import ClientError

        try:
            self._client().download_file(self.bucket, key, str(dest))
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                raise FileNotFoundError(key) from exc
            raise

    def upload(self, key: str, src: Path) -> None:
        self._client().upload_file(str(src), self.bucket, key)


def minisign_verify(tarball: Path, sig: Path, pubkey: Path) -> bool:
    r = subprocess.run(
        ["minisign", "-V", "-q", "-p", str(pubkey), "-x", str(sig), "-m", str(tarball)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return r.returncode == 0


def sudo_apply(verb: str, *args: str) -> tuple[int, str]:
    r = subprocess.run(
        ["sudo", "-n", "/opt/hacklab/bin/hacklab-apply", verb, *args],
        capture_output=True,
        text=True,
        timeout=900,
    )
    return r.returncode, (r.stdout + r.stderr).strip()
