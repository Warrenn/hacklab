"""Flasher: detect -> compile -> upload (bootloader fallback, cached) -> verify."""

from pathlib import Path

import pytest

from hacklab.board import FakeBoard
from hacklab.flash import Flasher


@pytest.fixture
def sketch(tmp_path: Path) -> Path:
    d = tmp_path / "sk"
    d.mkdir()
    (d / "sk.ino").write_text("void setup(){} void loop(){}")
    return d


def make(tmp_path: Path, board: FakeBoard) -> Flasher:
    return Flasher(board, data_dir=tmp_path / "data", reenumerate_timeout=0.3, sleep=lambda s: None)


def test_happy_path_reports_stages_and_cpu(tmp_path: Path, sketch: Path):
    fb = FakeBoard()
    stages: list[str] = []
    res = make(tmp_path, fb).flash("b", sketch, progress=stages.append)
    assert res.ok is True
    assert stages == ["compiling", "uploading", "verifying"]
    assert res.cpu == "atmega328" and res.port == "/dev/ttyFAKE0"
    assert "text" in res.log  # compile sizes recorded


def test_no_board_fails_before_compiling(tmp_path: Path, sketch: Path):
    fb = FakeBoard()
    fb.unplugged = True
    res = make(tmp_path, fb).flash("b", sketch, progress=lambda s: None)
    assert res.ok is False and res.failed_stage == "detecting"
    assert "plugged in" in res.message_kid
    assert fb.compiles == 0


def test_compile_error_fails_with_log_and_no_upload(tmp_path: Path, sketch: Path):
    fb = FakeBoard()
    fb.compile_error = "error: expected ';'"
    res = make(tmp_path, fb).flash("b", sketch, progress=lambda s: None)
    assert res.ok is False and res.failed_stage == "compiling"
    assert "expected ';'" in res.log and fb.uploads == 0


def test_old_bootloader_fallback_is_cached_per_box(tmp_path: Path, sketch: Path):
    fb = FakeBoard()
    fb.upload_fails_for = {"atmega328"}
    f = make(tmp_path, fb)
    res = f.flash("forklift", sketch, progress=lambda s: None)
    assert res.ok and res.cpu == "atmega328old" and fb.uploads == 2
    # second flash goes straight to the cached cpu
    res2 = Flasher(
        fb, data_dir=tmp_path / "data", reenumerate_timeout=0.3, sleep=lambda s: None
    ).flash("forklift", sketch, progress=lambda s: None)
    assert res2.ok and res2.cpu == "atmega328old" and fb.uploads == 3
    # another box is not affected by the cache
    fb.upload_fails_for = set()
    assert f.flash("turret", sketch, progress=lambda s: None).cpu == "atmega328"


def test_both_bootloaders_failing_is_an_upload_failure(tmp_path: Path, sketch: Path):
    fb = FakeBoard()
    fb.upload_fails_for = {"atmega328", "atmega328old"}
    res = make(tmp_path, fb).flash("b", sketch, progress=lambda s: None)
    assert res.ok is False and res.failed_stage == "uploading" and fb.uploads == 2


def test_port_vanishing_after_upload_fails_verification(tmp_path: Path, sketch: Path):
    fb = FakeBoard()
    fb.vanish_after_upload = True
    res = make(tmp_path, fb).flash("b", sketch, progress=lambda s: None)
    assert res.ok is False and res.failed_stage == "verifying"
    assert "wake up" in res.message_kid


def test_detect_returns_port_or_none(tmp_path: Path):
    fb = FakeBoard()
    assert make(tmp_path, fb).detect().address == "/dev/ttyFAKE0"
    fb.unplugged = True
    assert make(tmp_path, fb).detect() is None


def test_detect_is_cached_briefly(tmp_path: Path):
    """/api/status polls detect(); a real `board list` costs ~10 s on a Pi 3."""
    fb = FakeBoard()
    calls = {"n": 0}
    orig = fb.list_ports

    def counting():
        calls["n"] += 1
        return orig()

    fb.list_ports = counting
    now = {"t": 1000.0}
    f = Flasher(
        fb,
        data_dir=tmp_path / "data",
        reenumerate_timeout=0.3,
        sleep=lambda s: None,
        clock=lambda: now["t"],
    )
    assert f.detect() is not None and f.detect() is not None
    assert calls["n"] == 1  # second call served from the cache
    now["t"] += 15
    f.detect()
    assert calls["n"] == 2  # cache expired
    fb.unplugged = True
    assert f.detect(fresh=True) is None and calls["n"] == 3  # flash() always asks for a fresh look
