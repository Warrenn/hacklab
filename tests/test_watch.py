"""Plug/unplug shows on the page within a second: the server watches the serial
device nodes and pushes a status event over the SSE feed (no 20 s poll wait)."""

import time
from pathlib import Path

from fastapi.testclient import TestClient

from hacklab.app import create_app
from hacklab.board import ArduinoCli, FakeBoard
from hacklab.config import Config
from tests.conftest import write_box


def test_fake_board_device_nodes_follow_unplugged():
    fb = FakeBoard()
    assert fb.device_nodes() == frozenset({"/dev/ttyFAKE0"})
    fb.unplugged = True
    assert fb.device_nodes() == frozenset()


def test_cli_device_nodes_are_a_cheap_glob(tmp_path: Path, monkeypatch):
    cli = ArduinoCli("/nonexistent/arduino-cli", None)
    monkeypatch.setattr(cli, "device_globs", (str(tmp_path / "ttyUSB*"), str(tmp_path / "ttyACM*")))
    assert cli.device_nodes() == frozenset()
    (tmp_path / "ttyUSB0").touch()
    (tmp_path / "ttyACM3").touch()
    assert cli.device_nodes() == frozenset({str(tmp_path / "ttyUSB0"), str(tmp_path / "ttyACM3")})


def drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def test_unplug_refreshes_status_and_pushes_event(tmp_path: Path):
    root = tmp_path / "boxes"
    write_box(root, "nanobox")
    fb = FakeBoard()
    cfg = Config(data_dir=tmp_path / "data", fake_board=False, boxes_dir=root, watch_interval=0.02)
    app = create_app(cfg, board=fb)
    with TestClient(app) as c:
        c.post("/api/box", json={"id": "nanobox"})
        assert c.get("/api/status").json()["board_connected"] is True
        q = app.state.runner.subscribe()
        fb.unplugged = True
        # detection is cached for 10 s: only the watcher can flip this within a second
        deadline = time.monotonic() + 2
        while c.get("/api/status").json()["board_connected"] and time.monotonic() < deadline:
            time.sleep(0.02)
        assert c.get("/api/status").json()["board_connected"] is False
        time.sleep(0.05)
        assert {"type": "status"} in drain(q)
        fb.unplugged = False
        deadline = time.monotonic() + 2
        while not c.get("/api/status").json()["board_connected"] and time.monotonic() < deadline:
            time.sleep(0.02)
        assert c.get("/api/status").json()["board_connected"] is True
        assert {"type": "status"} in drain(q)
