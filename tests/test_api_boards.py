"""Per-box board spec: detection and flashing follow the profile's fqbn (P6 registry)."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hacklab.app import create_app
from hacklab.board import FakeBoard, Port
from hacklab.config import Config
from hacklab.jobs import TERMINAL_STATES
from hacklab.profiles import ProfileError, load_boxes
from tests.conftest import write_box

ESP32_PORT = Port("/dev/ttyACM0", "0x303a", "0x1001", "esp-serial-1")


def settle(c, job_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["state"] in TERMINAL_STATES:
            return j
        time.sleep(0.01)
    raise AssertionError("job did not finish")


@pytest.fixture
def two_boxes(tmp_path: Path):
    root = tmp_path / "boxes"
    write_box(root, "nanobox")
    write_box(root, "espbox", fqbn="esp32:esp32:esp32")
    return root


def test_profile_fqbn_must_be_a_registry_key(tmp_path: Path):
    root = tmp_path / "boxes"
    write_box(root, "weird", fqbn="acme:chip:board")
    with pytest.raises(ProfileError, match="acme:chip:board"):
        load_boxes(root)


def test_detection_and_flash_follow_the_selected_box(two_boxes, tmp_path, monkeypatch):
    import hacklab.flash

    monkeypatch.setattr(hacklab.flash, "DETECT_TTL", 0.0)
    fb = FakeBoard()
    fb.port = ESP32_PORT  # an ESP32 dev board is plugged in
    fb.reenumerate_gap = 1  # native USB: vanishes once after upload
    cfg = Config(data_dir=tmp_path / "data", fake_board=False, boxes_dir=two_boxes)
    with TestClient(create_app(cfg, board=fb)) as c:
        c.post("/api/box", json={"id": "nanobox"})
        assert c.get("/api/status").json()["board_connected"] is False  # not a Nano
        c.post("/api/box", json={"id": "espbox"})
        assert c.get("/api/status").json()["board_connected"] is True
        j = settle(
            c,
            c.post("/api/flash/sketch", json={"source": "void setup(){} void loop(){}"}).json()[
                "job_id"
            ],
        )
        assert j["state"] == "done"
        assert fb.last_fqbn == "esp32:esp32:esp32"  # bare fqbn, no cpu option
        # and a Nano box still gets the cpu option
        fb.port = Port("/dev/ttyUSB0", "0x1a86", "0x7523", "")
        fb.reenumerate_gap = 0
        c.post("/api/box", json={"id": "nanobox"})
        j = settle(
            c,
            c.post("/api/flash/sketch", json={"source": "void setup(){} void loop(){}"}).json()[
                "job_id"
            ],
        )
        assert j["state"] == "done" and fb.last_fqbn == "arduino:avr:nano:cpu=atmega328"
