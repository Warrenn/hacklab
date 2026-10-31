"""Plug/unplug shows on the page within a second: the server watches the serial
device nodes and pushes a status event over the SSE feed (no 20 s poll wait)."""

import time
from pathlib import Path

from fastapi.testclient import TestClient

from hacklab.app import create_app
from hacklab.board import ArduinoCli, FakeBoard, Port
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


def fake_sysfs(root: Path, name: str, vid: str, pid: str, serial: str | None):
    """/sys/class/tty/<name>/device -> .../<usb>/<usb>:1.0[/<name>], idVendor two levels up."""
    usb = root / "devices" / "1-1.2"
    iface = usb / "1-1.2:1.0" / name
    iface.mkdir(parents=True)
    (usb / "idVendor").write_text(vid + "\n")
    (usb / "idProduct").write_text(pid + "\n")
    if serial is not None:
        (usb / "serial").write_text(serial + "\n")
    cls = root / "class" / "tty" / name
    cls.mkdir(parents=True)
    (cls / "device").symlink_to(iface)
    return root / "class" / "tty"


def test_cli_lists_ports_from_sysfs_without_arduino_cli(tmp_path: Path):
    cli = ArduinoCli("/nonexistent/arduino-cli", None)  # would fail if board list ran
    cli.sysfs_tty = fake_sysfs(tmp_path, "ttyUSB0", "1A86", "7523", None)
    assert cli.list_ports() == [Port("/dev/ttyUSB0", "0x1a86", "0x7523", "")]
    cli.sysfs_tty = fake_sysfs(tmp_path / "b", "ttyACM0", "303a", "1001", "esp-1")
    assert cli.list_ports() == [Port("/dev/ttyACM0", "0x303a", "0x1001", "esp-1")]


def test_cli_sysfs_ignores_ttys_without_a_usb_parent(tmp_path: Path):
    cli = ArduinoCli("/nonexistent/arduino-cli", None)
    tty = tmp_path / "class" / "tty"
    (tty / "ttyAMA0").mkdir(parents=True)  # the Pi's own UART: no idVendor anywhere above
    (tty / "ttyAMA0" / "device").symlink_to(tmp_path / "devices" / "soc")
    (tmp_path / "devices" / "soc").mkdir(parents=True)
    cli.sysfs_tty = tty
    assert cli.list_ports() == []


def test_a_board_that_needs_a_moment_to_settle_is_seen_connected_by_the_watcher(tmp_path: Path):
    # owner 2026-10-31: "disconnected was fast but connecting was slow". A fresh USB device
    # shows up in /dev before its sysfs parent is ready; the first detection says "nothing",
    # and nothing re-checked until the poll. The watcher now looks again after a short settle.
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
        deadline = time.monotonic() + 2  # let the watcher itself notice the unplug (its event)
        while {"type": "status"} not in drain(q) and time.monotonic() < deadline:
            time.sleep(0.05)
        fb.unplugged = False
        fb._gap = 1  # the node is there, the first listing still shows no port
        deadline = time.monotonic() + 4
        while not c.get("/api/status").json()["board_connected"] and time.monotonic() < deadline:
            time.sleep(0.05)
        assert c.get("/api/status").json()["board_connected"] is True
        time.sleep(0.05)
        assert drain(q).count({"type": "status"}) >= 2  # at the change, and again after settling
