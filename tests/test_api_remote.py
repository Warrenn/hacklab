"""Remote-view policy: reads always, writes only when helping; toggle only from remote."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hacklab import remote as remote_mod
from hacklab.app import create_app
from hacklab.board import FakeBoard
from hacklab.config import Config
from hacklab.genie import FakeGenieClient
from hacklab.jobs import TERMINAL_STATES
from tests.test_genie import golden

REMOTE = {
    "X-Hacklab-Source": "remote"
}  # honoured by the real runner only through the test hook below


@pytest.fixture
def app(tmp_path: Path, boxes_dir: Path, monkeypatch):
    # tests run as 'testclient' (local); the test hook lets a header pick the source
    monkeypatch.setattr(remote_mod, "TRUST_SOURCE_HEADER", True)
    cfg = Config(data_dir=tmp_path / "data", fake_board=False, boxes_dir=boxes_dir, api_key="k")
    return create_app(
        cfg, board=FakeBoard(), genie_client=FakeGenieClient(golden("fire-when-3-pressed"))
    )


def settle(c, job_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["state"] in TERMINAL_STATES:
            return j
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_status_reports_source_and_helping(app):
    with TestClient(app) as c:
        st = c.get("/api/status").json()
        assert st["source"] == "local" and st["helping"] is False
        assert c.get("/api/status", headers=REMOTE).json()["source"] == "remote"


def test_remote_reads_ok_writes_blocked_until_helping(app):
    with TestClient(app) as c:
        assert c.get("/api/boxes", headers=REMOTE).status_code == 200
        r = c.post("/api/box", json={"id": "testbox"}, headers=REMOTE)
        assert r.status_code == 403 and "Remote view only" in r.json()["detail"]
        c.post("/api/box", json={"id": "testbox"})  # local picks the box
        for path, body in [
            ("/api/ask", {"text": "x"}),
            ("/api/undo", None),
            ("/api/reset", None),
            ("/api/flash/behaviour", {"id": "shake"}),
            ("/api/flash/sketch", {"source": "x"}),
        ]:
            r = (
                c.post(path, json=body, headers=REMOTE)
                if body is not None
                else c.post(path, headers=REMOTE)
            )
            assert r.status_code == 403, path
        assert c.get("/api/behaviours", headers=REMOTE).status_code == 200
        assert c.get("/api/sketch/current", headers=REMOTE).status_code == 200


def test_helping_toggle_only_from_remote(app):
    with TestClient(app) as c:
        assert c.post("/api/helping", json={"on": True}).status_code == 403  # local: no such switch
        r = c.post("/api/helping", json={"on": True}, headers=REMOTE)
        assert r.status_code == 200 and r.json()["helping"] is True
        assert c.get("/api/status").json()["helping"] is True  # the kid's screen sees it
        assert c.post("/api/box", json={"id": "testbox"}, headers=REMOTE).status_code == 200
        j = settle(
            c, c.post("/api/ask", json={"text": "fire on 3"}, headers=REMOTE).json()["job_id"]
        )
        assert j["state"] == "done"
        assert c.post("/api/helping", json={"on": False}, headers=REMOTE).json()["helping"] is False
        assert c.post("/api/undo", headers=REMOTE).status_code == 403


def test_helping_auto_off_after_two_hours(app, monkeypatch):
    now = {"t": 1000.0}
    monkeypatch.setattr(remote_mod, "clock", lambda: now["t"])
    with TestClient(app) as c:
        c.post("/api/helping", json={"on": True}, headers=REMOTE)
        now["t"] += 2 * 3600 + 1
        assert c.get("/api/status").json()["helping"] is False
        assert c.post("/api/box", json={"id": "testbox"}, headers=REMOTE).status_code == 403


def test_flips_are_logged_and_jobs_carry_source(app, tmp_path):
    with TestClient(app) as c:
        c.post("/api/helping", json={"on": True}, headers=REMOTE)
        c.post("/api/box", json={"id": "testbox"}, headers=REMOTE)
        settle(c, c.post("/api/ask", json={"text": "fire on 3"}, headers=REMOTE).json()["job_id"])
    flips = (tmp_path / "data" / "helping.jsonl").read_text()
    assert '"on": true' in flips and '"peer"' in flips
    asks = (tmp_path / "data" / "testbox" / "logs" / "asks.jsonl").read_text()
    assert '"source": "tailscale"' in asks


def test_events_announce_helping_changes(app):
    from hacklab.app import format_sse  # noqa: F401 - the SSE route is exercised by the pw tests

    with TestClient(app) as c:
        r = c.post("/api/helping", json={"on": True}, headers=REMOTE)
        assert r.json() == {"helping": True}


def test_header_ignored_without_the_test_hook(tmp_path, boxes_dir, monkeypatch):
    monkeypatch.setattr(remote_mod, "TRUST_SOURCE_HEADER", False)
    cfg = Config(data_dir=tmp_path / "data", fake_board=False, boxes_dir=boxes_dir)
    with TestClient(create_app(cfg, board=FakeBoard())) as c:
        assert c.get("/api/status", headers=REMOTE).json()["source"] == "local"
        assert c.post("/api/box", json={"id": "testbox"}, headers=REMOTE).status_code == 200


def test_mock_backend_honours_the_header(tmp_path, boxes_dir):
    cfg = Config(data_dir=tmp_path / "data", fake_board=True, boxes_dir=boxes_dir, api_key="k")
    with TestClient(create_app(cfg)) as c:
        assert c.get("/api/status", headers=REMOTE).json()["source"] == "remote"
        assert c.post("/api/box", json={"id": "testbox"}, headers=REMOTE).status_code == 403
