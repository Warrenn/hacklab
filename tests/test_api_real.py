"""App wiring with the real runner on a FakeBoard (FAKE_BOARD=0 path)."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hacklab.app import create_app
from hacklab.board import FakeBoard
from hacklab.config import Config
from hacklab.jobs import TERMINAL_STATES


@pytest.fixture
def fb() -> FakeBoard:
    return FakeBoard()


@pytest.fixture
def client(tmp_path: Path, fb: FakeBoard):
    cfg = Config(data_dir=tmp_path / "data", fake_board=False)
    with TestClient(create_app(cfg, board=fb)) as c:
        yield c


def settle(client: TestClient, job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["state"] in TERMINAL_STATES:
            return j
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_status_reports_real_board_detection(client, fb):

    assert client.get("/api/status").json()["board_connected"] is True
    fb.unplugged = True
    assert client.get("/api/status").json()["board_connected"] is True  # cached for DETECT_TTL


def test_status_sees_an_unplugged_board_once_the_cache_expires(tmp_path, fb, monkeypatch):
    import hacklab.flash

    monkeypatch.setattr(hacklab.flash, "DETECT_TTL", 0.0)
    cfg = Config(data_dir=tmp_path / "data", fake_board=False)
    with TestClient(create_app(cfg, board=fb)) as c:
        assert c.get("/api/status").json()["board_connected"] is True
        fb.unplugged = True
        assert c.get("/api/status").json()["board_connected"] is False


def test_select_box_creates_baseline_and_flash_undo_reset_persist(client, tmp_path):
    client.post("/api/box", json={"id": "ir-turret"})
    st = client.get("/api/status").json()
    assert st["current_version"] == "0000" and st["versions_count"] == 1
    j = settle(
        client, client.post("/api/flash/sketch", json={"source": "void loop(){}"}).json()["job_id"]
    )
    assert j["state"] == "done"
    assert client.get("/api/sketch/current").json() == {
        "source": "void loop(){}",
        "version": "0001",
        "box": "ir-turret",
    }
    j = settle(client, client.post("/api/undo").json()["job_id"])
    assert j["state"] == "done"
    assert client.get("/api/status").json()["current_version"] == "0000"
    assert client.post("/api/undo").status_code == 409
    assert (tmp_path / "data" / "ir-turret" / "versions" / "0000").is_dir()


def test_reset_after_several_changes(client, tmp_path):
    client.post("/api/box", json={"id": "ir-turret"})
    for src in ("a", "b"):
        assert (
            settle(client, client.post("/api/flash/sketch", json={"source": src}).json()["job_id"])[
                "state"
            ]
            == "done"
        )
    assert settle(client, client.post("/api/reset").json()["job_id"])["state"] == "done"
    st = client.get("/api/status").json()
    assert st["current_version"] == "0000" and st["versions_count"] == 1


def test_root_serves_html(client):
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
