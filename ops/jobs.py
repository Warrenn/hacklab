"""Job executor for the ops agent (STRATEGY.md P5c). Pure logic, no AWS SDK:
the agent injects an S3 client, a signature verifier and the sudo helper
runner so this file is unit-tested without a device.

Allowlist: deploy <version>, rollback, restart, upload-logs, report-state,
apt-upgrade. Anything else is rejected. Nothing in a job document is ever
run as a command; `version` is only used to name S3 keys and is passed as a
single argument to the root helper after the signature verified.
"""

from __future__ import annotations

import io
import re
import tarfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+-]{0,63}$")
OPS = ("deploy", "rollback", "restart", "upload-logs", "report-state", "apt-upgrade")


@dataclass
class Result:
    ok: bool
    rejected: bool = False
    details: dict[str, str] = field(default_factory=dict)


def _last_line(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines[-1] if lines else ""


class JobExecutor:
    def __init__(
        self,
        thing: str,
        releases_dir: Path,
        logs_dir: Path,
        pubkey: Path,
        s3,
        apply: Callable[..., tuple[int, str]],
        verify: Callable[[Path, Path, Path], bool],
    ):
        self.thing, self.releases_dir, self.logs_dir, self.pubkey = (
            thing,
            Path(releases_dir),
            Path(logs_dir),
            Path(pubkey),
        )
        self.s3, self.apply, self.verify = s3, apply, verify

    def run(self, doc: dict, progress: Callable[[str], None]) -> Result:
        op = doc.get("op") if isinstance(doc, dict) else None
        if op not in OPS:
            return Result(False, rejected=True, details={"reason": f"unknown op {op!r}"})
        try:
            return getattr(self, "_" + op.replace("-", "_"))(doc, progress)
        except Exception as exc:  # noqa: BLE001 - the job must end FAILED, never crash the agent
            return Result(False, details={"reason": f"{type(exc).__name__}: {str(exc)[:300]}"})

    # -- ops ---------------------------------------------------------------
    def _deploy(self, doc, progress) -> Result:
        version = str(doc.get("version", ""))
        if not VERSION_RE.match(version):
            return Result(False, rejected=True, details={"reason": f"bad version {version!r}"})
        name = f"hacklab-{version}.tar.gz"
        self.releases_dir.mkdir(parents=True, exist_ok=True)
        tarball, sig = self.releases_dir / name, self.releases_dir / f"{name}.minisig"
        progress("downloading")
        try:
            self.s3.download(f"releases/{version}/{name}", tarball)
            self.s3.download(f"releases/{version}/{name}.minisig", sig)
        except FileNotFoundError as exc:
            return Result(
                False, details={"reason": f"release {version} not found in the bucket: {exc}"}
            )
        progress("verifying")
        if not self.verify(tarball, sig, self.pubkey):
            tarball.unlink(missing_ok=True)
            sig.unlink(missing_ok=True)
            return Result(
                False, details={"reason": f"signature of {name} did not verify; discarded"}
            )
        progress("applying")
        rc, out = self.apply("deploy", version)
        details = {"release": version, "helper": out[-800:]}
        if rc != 0:
            details["reason"] = _last_line(out) or f"hacklab-apply exited {rc}"
            return Result(False, details=details)
        return Result(True, details=details)

    def _simple(self, verb, progress) -> Result:
        progress("applying")
        rc, out = self.apply(verb)
        details = {"helper": out[-800:]}
        if rc != 0:
            details["reason"] = _last_line(out) or f"hacklab-apply exited {rc}"
            return Result(False, details=details)
        return Result(True, details=details)

    def _rollback(self, doc, progress):
        return self._simple("rollback", progress)

    def _restart(self, doc, progress):
        return self._simple("restart", progress)

    def _apt_upgrade(self, doc, progress):
        return self._simple("apt-upgrade", progress)

    def _report_state(self, doc, progress) -> Result:
        return Result(True, details={"reported": "shadow heartbeat"})

    def _upload_logs(self, doc, progress) -> Result:
        progress("bundling")
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as t:
            for f in sorted(self.logs_dir.rglob("*")):
                if f.is_file() and f.suffix in (".jsonl", ".log", ".gz"):
                    t.add(f, arcname=str(f.relative_to(self.logs_dir)))
        bundle = self.logs_dir / f"bundle-{int(time.time())}.tar.gz"
        bundle.write_bytes(buf.getvalue())
        key = f"logs/{self.thing}/{bundle.name}"
        progress("uploading")
        try:
            self.s3.upload(key, bundle)
        finally:
            bundle.unlink(missing_ok=True)
        return Result(True, details={"key": key, "bytes": str(len(buf.getvalue()))})
