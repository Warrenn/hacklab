"""ops agent job handling: allowlist, progress, signature gate, results. No AWS, no root."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ops"))
import jobs as opsjobs  # noqa: E402  (ops/jobs.py, the agent's job executor)


class FakeS3:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects
        self.uploaded: dict[str, bytes] = {}

    def download(self, key: str, dest: Path) -> None:
        if key not in self.objects:
            raise FileNotFoundError(key)
        dest.write_bytes(self.objects[key])

    def upload(self, key: str, src: Path) -> None:
        self.uploaded[key] = src.read_bytes()


class FakeApply:
    """Stands in for `sudo /opt/hacklab/bin/hacklab-apply <verb> [arg]`."""

    def __init__(self, results: dict[str, tuple[int, str]] | None = None):
        self.calls: list[list[str]] = []
        self.results = results or {}

    def __call__(self, verb: str, *args: str) -> tuple[int, str]:
        self.calls.append([verb, *args])
        return self.results.get(verb, (0, f"{verb} ok"))


class FakeVerify:
    def __init__(self, ok: bool = True):
        self.ok, self.calls = ok, []

    def __call__(self, tarball: Path, sig: Path, pubkey: Path) -> bool:
        self.calls.append((tarball.name, sig.name))
        return self.ok


@pytest.fixture
def env(tmp_path: Path):
    s3 = FakeS3(
        {
            "releases/0.2.0/hacklab-0.2.0.tar.gz": b"TARBALL",
            "releases/0.2.0/hacklab-0.2.0.tar.gz.minisig": b"SIG",
        }
    )
    apply = FakeApply()
    verify = FakeVerify()
    ex = opsjobs.JobExecutor(
        thing="hacklab-pi3",
        releases_dir=tmp_path / "releases",
        logs_dir=tmp_path / "logs",
        pubkey=tmp_path / "minisign.pub",
        s3=s3,
        apply=apply,
        verify=verify,
    )
    (tmp_path / "minisign.pub").write_text("pub")
    return s3, apply, verify, ex


def test_deploy_downloads_verifies_then_applies(env, tmp_path):
    s3, apply, verify, ex = env
    progress = []
    result = ex.run({"op": "deploy", "version": "0.2.0"}, progress=progress.append)
    assert result.ok and result.details["release"] == "0.2.0"
    assert (tmp_path / "releases" / "hacklab-0.2.0.tar.gz").read_bytes() == b"TARBALL"
    assert verify.calls == [("hacklab-0.2.0.tar.gz", "hacklab-0.2.0.tar.gz.minisig")]
    assert apply.calls == [["deploy", "0.2.0"]]
    assert progress[:2] == ["downloading", "verifying"] and progress[-1] == "applying"


def test_bad_signature_never_reaches_the_helper(env):
    s3, apply, verify, ex = env
    verify.ok = False
    result = ex.run({"op": "deploy", "version": "0.2.0"}, progress=lambda s: None)
    assert not result.ok and "signature" in result.details["reason"]
    assert apply.calls == []


def test_missing_release_fails_cleanly(env):
    s3, apply, verify, ex = env
    result = ex.run({"op": "deploy", "version": "9.9.9"}, progress=lambda s: None)
    assert not result.ok and "9.9.9" in result.details["reason"] and apply.calls == []


def test_helper_failure_is_reported_with_its_output(env):
    s3, apply, verify, ex = env
    apply.results["deploy"] = (
        1,
        "[apply] verifying\n[apply] extracting\nhealth check failed; rolled back to 0.1.0",
    )
    result = ex.run({"op": "deploy", "version": "0.2.0"}, progress=lambda s: None)
    assert not result.ok and result.details["reason"] == "health check failed; rolled back to 0.1.0"
    assert "[apply] extracting" in result.details["helper"]  # full output kept separately


@pytest.mark.parametrize("op", ["rollback", "restart", "apt-upgrade"])
def test_simple_ops_call_the_helper_verb(env, op):
    s3, apply, verify, ex = env
    assert ex.run({"op": op}, progress=lambda s: None).ok
    assert apply.calls == [[op]]


def test_unknown_op_is_rejected_and_nothing_runs(env):
    s3, apply, verify, ex = env
    for doc in ({"op": "shell", "cmd": "rm -rf /"}, {"op": "deploy; reboot"}, {}, {"version": "1"}):
        result = ex.run(doc, progress=lambda s: None)
        assert result.rejected and not result.ok
    assert apply.calls == [] and verify.calls == []


def test_upload_logs_bundles_and_uploads(env, tmp_path):
    s3, apply, verify, ex = env
    (tmp_path / "logs" / "omnibot-forklift" / "logs").mkdir(parents=True)
    (tmp_path / "logs" / "omnibot-forklift" / "logs" / "asks.jsonl").write_text('{"a":1}\n')
    result = ex.run({"op": "upload-logs"}, progress=lambda s: None)
    assert result.ok
    ((key, blob),) = s3.uploaded.items()
    assert key.startswith("logs/hacklab-pi3/") and key.endswith(".tar.gz") and len(blob) > 50
    assert result.details["key"] == key


def test_report_state_is_a_no_op_success(env):
    s3, apply, verify, ex = env
    assert ex.run({"op": "report-state"}, progress=lambda s: None).ok and apply.calls == []


def test_status_details_are_strings(env):
    """IoT status_details values must be strings."""
    s3, apply, verify, ex = env
    result = ex.run({"op": "deploy", "version": "0.2.0"}, progress=lambda s: None)
    assert all(isinstance(v, str) for v in result.details.values())
    json.dumps(result.details)
