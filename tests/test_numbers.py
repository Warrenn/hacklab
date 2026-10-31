"""P8 round 4: Level 2 on the box's own code. The IDE's ///{...} markers in every file of
the current version are the kid's sliders; sending renders them into a copy and flashes it."""

import time

from fastapi.testclient import TestClient

from hacklab.app import create_app
from hacklab.board import FakeBoard
from hacklab.config import Config
from hacklab.jobs import TERMINAL_STATES
from hacklab.templates import find_tweakables


def settle(c, job_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["state"] in TERMINAL_STATES:
            return j
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_a_marker_carries_the_authors_comment_as_a_hint():
    (t,) = find_tweakables('int top = 100; // the top -- ///{"min":0,"max":200}\n')
    assert t.hint == "the top" and t.to_api()["hint"] == "the top"
    (u,) = find_tweakables('bool flip = false; ///{"options":["true","false"]}\n')
    assert u.hint is None and "hint" not in u.to_api()


def test_tweakables_come_from_every_file_of_the_current_version(tmp_path, boxes_dir):
    cfg = Config(data_dir=tmp_path / "data", fake_board=False, boxes_dir=boxes_dir)
    with TestClient(create_app(cfg, board=FakeBoard())) as c:
        assert c.get("/api/tweakables").status_code == 409  # no box yet
        c.post("/api/box", json={"id": "testbox"})
        files = c.get("/api/tweakables").json()["files"]
        assert [f["name"] for f in files] == ["stock.ino", "config.h"]  # main first
        assert "void setup" in files[0]["source"] and "int top" in files[1]["source"]
        assert [t["name"] for t in files[0]["tweakables"]] == ["speed"]
        assert files[0]["tweakables"][0]["hint"] == "how fast"
        assert [t["name"] for t in files[1]["tweakables"]] == ["top", "flip"]
        assert files[1]["tweakables"][0]["range"] == [0, 200]


def test_sending_numbers_renders_every_file_and_saves_a_version(tmp_path, boxes_dir):
    cfg = Config(data_dir=tmp_path / "data", fake_board=False, boxes_dir=boxes_dir)
    fb = FakeBoard()
    with TestClient(create_app(cfg, board=fb)) as c:
        c.post("/api/box", json={"id": "testbox"})
        bad = c.post("/api/flash/numbers", json={"values": {"nope": 1}})
        assert bad.status_code == 422
        r = c.post("/api/flash/numbers", json={"values": {"speed": 9, "top": 150, "flip": "true"}})
        job = settle(c, r.json()["job_id"])
        assert job["state"] == "done" and job["kind"] == "flash"
        st = c.get("/api/status").json()
        assert st["versions_count"] == 2 and st["current_note"] == "My numbers"
        assert "config.h" in fb.last_sketch_files  # the sibling travelled with the main file
        (vdir,) = (tmp_path / "data" / "testbox" / "versions" / "0001").glob("*/")
        assert "int speed = 9;" in (vdir / "stock.ino").read_text()
        cfg_h = (vdir / "config.h").read_text()
        assert "int top = 150;" in cfg_h and "bool flip = true;" in cfg_h
        # the sliders now show the new numbers (they read the current version)
        files = c.get("/api/tweakables").json()["files"]
        assert files[1]["tweakables"][0]["value"] == 150


def test_mock_mode_serves_the_stock_numbers_and_flashes(tmp_path, boxes_dir):
    cfg = Config(data_dir=tmp_path / "data", fake_board=True, boxes_dir=boxes_dir)
    with TestClient(create_app(cfg)) as c:
        c.post("/api/box", json={"id": "testbox"})
        files = c.get("/api/tweakables").json()["files"]
        assert [t["name"] for f in files for t in f["tweakables"]] == ["speed", "top", "flip"]
        r = c.post("/api/flash/numbers", json={"values": {"top": 120}})
        assert settle(c, r.json()["job_id"])["state"] == "done"
        assert c.get("/api/status").json()["versions_count"] == 2
