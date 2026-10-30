"""release.sh builds a signed tarball with a manifest; verify with the public key."""

import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(shutil.which("minisign") is None, reason="minisign not installed")


@pytest.fixture
def throwaway_key(tmp_path: Path):
    """A passphrase-less key just for the test (the real key is passphrase-protected)."""
    subprocess.run(
        ["minisign", "-G", "-W", "-f", "-p", str(tmp_path / "pub"), "-s", str(tmp_path / "key")],
        check=True,
        capture_output=True,
    )
    return tmp_path / "key", tmp_path / "pub"


def test_release_builds_signed_tarball_and_manifest(tmp_path: Path, throwaway_key):
    key, pub = throwaway_key
    env = {
        **os.environ,
        "MINISIGN_KEY": str(key),
        "RELEASE_OUT": str(tmp_path / "out"),
        "RELEASE_NO_UPLOAD": "1",
    }
    r = subprocess.run(
        [str(ROOT / "scripts" / "release.sh"), "0.0.0-test"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr + r.stdout
    tarball = tmp_path / "out" / "hacklab-0.0.0-test.tar.gz"
    assert tarball.is_file() and (tmp_path / "out" / "hacklab-0.0.0-test.tar.gz.minisig").is_file()
    v = subprocess.run(
        ["minisign", "-V", "-p", str(pub), "-m", str(tarball)], capture_output=True, text=True
    )
    assert v.returncode == 0, v.stderr
    with tarfile.open(tarball) as t:
        names = t.getnames()
        manifest = json.load(t.extractfile("manifest.json"))
    assert manifest["version"] == "0.0.0-test" and manifest["git"] and manifest["built_at"]
    musts = ["hacklab/app.py", "boxes/ir-turret/profile.toml", "static/index.html"]
    for must in musts + ["provisioning/install.sh", "pyproject.toml"]:
        assert must in names and must in manifest["sha256"]
    assert not any(
        n.startswith((".env", "provisioning/local", "tests/pwa/screenshots")) for n in names
    )


def test_release_refuses_without_a_key(tmp_path: Path):
    env = {
        **os.environ,
        "MINISIGN_KEY": str(tmp_path / "missing"),
        "RELEASE_OUT": str(tmp_path / "out"),
        "RELEASE_NO_UPLOAD": "1",
    }
    r = subprocess.run(
        [str(ROOT / "scripts" / "release.sh"), "0.0.0-test"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0 and "key" in (r.stderr + r.stdout).lower()
