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


def test_stale_detect_returns_at_once_and_refreshes_in_the_background(tmp_path: Path):
    """Owner saw 'Let's go' do nothing: /api/status blocked ~10 s on `board list`
    once the cache expired. A stale cache must answer immediately."""
    import threading
    import time as _time

    fb = FakeBoard()
    orig = fb.list_ports
    gate = threading.Event()

    def slow():
        gate.wait(2)  # a slow `board list`
        return orig()

    fb.list_ports = slow
    now = {"t": 0.0}
    f = Flasher(fb, data_dir=tmp_path / "data", sleep=lambda s: None, clock=lambda: now["t"])
    gate.set()
    assert f.detect() is not None  # first call blocks (nothing cached yet)
    gate.clear()
    now["t"] += 60  # cache expired
    fb.unplugged = True
    t0 = _time.monotonic()
    assert f.detect() is not None  # stale answer, no wait
    assert _time.monotonic() - t0 < 0.5
    gate.set()  # let the background refresh finish
    for _ in range(50):
        if f.detect() is None:
            break
        _time.sleep(0.02)
    assert f.detect() is None  # refreshed value visible


# ---------- board registry (P6) ----------
from hacklab.board import BoardSpec, Port, board_spec  # noqa: E402


def test_flash_uses_the_spec_fqbn_candidates_in_order_and_caches(tmp_path: Path, sketch: Path):
    spec = BoardSpec(
        fqbn="x:y:z",
        core="x:y",
        cpu_options=("a", "b", "c"),
        usb_ids=frozenset({("0x1a86", "0x7523")}),
        reenumerates=False,
        upload_timeout=60,
        verified=True,
    )
    fb = FakeBoard()
    fb.upload_fails_for = {"a", "b"}
    f = make(tmp_path, fb)
    res = f.flash("box", sketch, progress=lambda s: None, spec=spec)
    assert res.ok and res.cpu == "c" and fb.uploads == 3
    assert fb.last_fqbn == "x:y:z:cpu=c"
    res2 = make(tmp_path, fb).flash("box", sketch, progress=lambda s: None, spec=spec)
    assert res2.ok and fb.uploads == 4  # cached option tried first


def test_esp32_spec_has_no_cpu_option_and_waits_for_reenumeration(tmp_path: Path, sketch: Path):
    esp = board_spec("esp32:esp32:esp32")
    fb = FakeBoard()
    fb.port = Port("/dev/ttyACM0", "0x303a", "0x1001", "ESP32-S3-ABC")
    fb.reenumerate_gap = 2  # port is gone for two listings after upload, then back
    stages: list[str] = []
    res = make(tmp_path, fb).flash("esp", sketch, progress=stages.append, spec=esp)
    assert res.ok and res.cpu is None and res.port == "/dev/ttyACM0"
    assert fb.last_fqbn == "esp32:esp32:esp32"
    assert stages == ["compiling", "uploading", "verifying"]
    assert not (tmp_path / "data" / "esp" / "board.json").exists()  # nothing to cache


def test_reenumerating_board_that_never_returns_fails_verification(tmp_path: Path, sketch: Path):
    esp = board_spec("esp32:esp32:esp32")
    fb = FakeBoard()
    fb.port = Port("/dev/ttyACM0", "0x303a", "0x1001", "")
    fb.vanish_after_upload = True
    res = make(tmp_path, fb).flash("esp", sketch, progress=lambda s: None, spec=esp)
    assert not res.ok and res.failed_stage == "verifying"


def test_reenumerating_board_that_never_vanishes_still_passes(tmp_path: Path, sketch: Path):
    """A fast reset can finish before the first listing; presence is what matters."""
    esp = board_spec("esp32:esp32:esp32")
    fb = FakeBoard()
    fb.port = Port("/dev/ttyACM0", "0x303a", "0x1001", "")
    assert make(tmp_path, fb).flash("esp", sketch, progress=lambda s: None, spec=esp).ok


def test_detect_with_a_spec_ignores_other_boards(tmp_path: Path):
    fb = FakeBoard()
    fb.port = Port("/dev/ttyUSB0", "0x0403", "0x6001", "A50285BI")  # FTDI: Nano family only
    assert make(tmp_path, fb).detect(spec=board_spec("esp32:esp32:esp32")) is None
    assert make(tmp_path, fb).detect(spec=board_spec("arduino:avr:nano")) is not None
