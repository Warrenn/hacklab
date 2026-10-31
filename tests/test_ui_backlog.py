"""P8 UI backlog, server side: the Home card's title + time, and the remembered box."""

import time

from fastapi.testclient import TestClient

from hacklab.app import create_app
from hacklab.board import FakeBoard
from hacklab.config import Config
from hacklab.jobs import TERMINAL_STATES


def settle(c, job_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["state"] in TERMINAL_STATES:
            return j
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_status_carries_the_current_versions_note_and_time_mock(tmp_path, boxes_dir):
    cfg = Config(data_dir=tmp_path / "data", fake_board=True, boxes_dir=boxes_dir)
    with TestClient(create_app(cfg)) as c:
        c.post("/api/box", json={"id": "testbox"})
        st = c.get("/api/status").json()
        assert st["current_note"] == "" and st["current_created"] is None  # stock: "How it came"
        job = c.post("/api/flash/behaviour", json={"id": "shake"}).json()
        settle(c, job["job_id"])
        st = c.get("/api/status").json()
        assert st["versions_count"] == 2
        assert st["current_note"] == "Shake"  # the trick's title
        assert abs(st["current_created"] - time.time()) < 60


def test_status_carries_the_current_versions_note_and_time_real(tmp_path, boxes_dir):
    cfg = Config(data_dir=tmp_path / "data", fake_board=False, boxes_dir=boxes_dir)
    with TestClient(create_app(cfg, board=FakeBoard())) as c:
        c.post("/api/box", json={"id": "testbox"})
        job = c.post("/api/flash/behaviour", json={"id": "shake"}).json()
        settle(c, job["job_id"])
        st = c.get("/api/status").json()
        assert st["current_note"] == "Shake"
        assert abs(st["current_created"] - time.time()) < 60


def test_selected_box_survives_a_restart(tmp_path, boxes_dir):
    cfg = Config(data_dir=tmp_path / "data", fake_board=False, boxes_dir=boxes_dir)
    with TestClient(create_app(cfg, board=FakeBoard())) as c:
        assert c.get("/api/status").json()["box"] is None
        c.post("/api/box", json={"id": "testbox"})
    with TestClient(create_app(cfg, board=FakeBoard())) as c:  # a deploy restarts the app
        assert c.get("/api/status").json()["box"] == "testbox"


def test_a_remembered_box_that_no_longer_exists_is_ignored(tmp_path, boxes_dir):
    cfg = Config(data_dir=tmp_path / "data", fake_board=False, boxes_dir=boxes_dir)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "selected.json").write_text('{"box": "gone-box"}')
    with TestClient(create_app(cfg, board=FakeBoard())) as c:
        assert c.get("/api/status").json()["box"] is None
