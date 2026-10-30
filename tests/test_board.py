"""arduino-cli wrapper (parsing recorded JSON through an injected runner) and FakeBoard."""

import json
from pathlib import Path

import pytest

from hacklab.board import ArduinoCli, CliError, FakeBoard, Port, find_board

# Recorded on the Pi 2026-10-30 (arduino-cli 1.5.1): CH340 clone, no serial number.
BOARD_LIST = {
    "detected_ports": [
        {
            "port": {
                "address": "/dev/ttyUSB0",
                "label": "/dev/ttyUSB0",
                "protocol": "serial",
                "protocol_label": "Serial Port (USB)",
                "properties": {"pid": "0x7523", "serialNumber": "", "vid": "0x1A86"},
            }
        },
        {
            "port": {
                "address": "/dev/ttyAMA0",
                "label": "/dev/ttyAMA0",
                "protocol": "serial",
                "protocol_label": "Serial Port",
            }
        },
    ]
}
COMPILE_OK = {
    "compiler_out": "Sketch uses 7838 bytes",
    "compiler_err": "",
    "builder_result": {
        "build_path": "/tmp/x",
        "executable_sections_size": [
            {"name": "text", "size": 7838, "max_size": 30720},
            {"name": "data", "size": 491, "max_size": 2048},
        ],
    },
    "success": True,
}
COMPILE_FAIL = {
    "compiler_out": "",
    "compiler_err": "sketch.ino:3:1: error: expected ';' before '}' token",
    "success": False,
}
UPLOAD_OK = {"stdout": "", "stderr": "", "updated_upload_port": {"address": "/dev/ttyUSB0"}}


class Recorder:
    """Stand-in for subprocess: records argv, replays canned (returncode, stdout, stderr)."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], timeout: float):
        self.calls.append(argv)
        rc, out = self.replies.pop(0)
        return rc, json.dumps(out) if isinstance(out, dict) else out, ""


def test_list_ports_parses_usb_ports_only():
    run = Recorder((0, BOARD_LIST))
    cli = ArduinoCli(
        "/opt/hacklab/bin/arduino-cli", "/opt/hacklab/arduino/arduino-cli.yaml", run=run
    )
    ports = cli.list_ports()
    assert ports == [Port(address="/dev/ttyUSB0", vid="0x1a86", pid="0x7523", serial="")]
    assert run.calls[0][:3] == [
        "/opt/hacklab/bin/arduino-cli",
        "--config-file",
        "/opt/hacklab/arduino/arduino-cli.yaml",
    ]
    assert "--json" in run.calls[0] and "list" in run.calls[0]


def test_find_board_prefers_known_nano_vid_pid():
    ports = [
        Port("/dev/ttyUSB1", "0x1234", "0x0001", ""),
        Port("/dev/ttyUSB0", "0x1a86", "0x7523", ""),
    ]
    assert find_board(ports).address == "/dev/ttyUSB0"
    assert find_board([]) is None
    assert find_board([Port("/dev/ttyUSB1", "0x1234", "0x0001", "")]) is None


def test_compile_ok_and_sizes(tmp_path: Path):
    run = Recorder((0, COMPILE_OK))
    cli = ArduinoCli("cli", None, run=run)
    res = cli.compile(tmp_path / "s", "arduino:avr:nano:cpu=atmega328", tmp_path / "out")
    assert res.ok is True
    assert res.sizes == {"text": (7838, 30720), "data": (491, 2048)}
    argv = run.calls[0]
    assert "compile" in argv and "--fqbn" in argv and "--output-dir" in argv and "--json" in argv
    assert str(tmp_path / "s") == argv[-1]


def test_compile_failure_keeps_compiler_log(tmp_path: Path):
    cli = ArduinoCli("cli", None, run=Recorder((1, COMPILE_FAIL)))
    res = cli.compile(tmp_path / "s", "arduino:avr:nano", tmp_path / "out")
    assert res.ok is False
    assert "expected ';'" in res.log


def test_upload_passes_port_fqbn_input_dir_verify(tmp_path: Path):
    run = Recorder((0, UPLOAD_OK))
    cli = ArduinoCli("cli", None, run=run)
    res = cli.upload(
        tmp_path / "s", "arduino:avr:nano:cpu=atmega328old", "/dev/ttyUSB0", tmp_path / "out"
    )
    assert res.ok is True
    argv = run.calls[0]
    for flag, val in [
        ("--fqbn", "arduino:avr:nano:cpu=atmega328old"),
        ("--port", "/dev/ttyUSB0"),
        ("--input-dir", str(tmp_path / "out")),
    ]:
        assert argv[argv.index(flag) + 1] == val
    assert "--verify" in argv


def test_upload_failure_has_avrdude_log(tmp_path: Path):
    run = Recorder((1, "avrdude: stk500_recv(): programmer is not responding"))
    res = ArduinoCli("cli", None, run=run).upload(
        tmp_path / "s", "f", "/dev/ttyUSB0", tmp_path / "o"
    )
    assert res.ok is False and "not responding" in res.log


def test_non_json_garbage_raises_cli_error(tmp_path: Path):
    cli = ArduinoCli("cli", None, run=Recorder((0, "not json")))
    with pytest.raises(CliError):
        cli.list_ports()


def test_fake_board_scripts_failures(tmp_path: Path):
    fb = FakeBoard()
    tmp_path = tmp_path / "sk"
    tmp_path.mkdir()
    (tmp_path / "sk.ino").write_text("")
    assert fb.list_ports()[0].address == "/dev/ttyFAKE0"
    assert fb.compile(tmp_path, "arduino:avr:nano:cpu=atmega328", tmp_path / "o").ok
    fb.compile_error = "error: 'foo' was not declared"
    r = fb.compile(tmp_path, "arduino:avr:nano:cpu=atmega328", tmp_path / "o")
    assert not r.ok and "foo" in r.log
    fb.compile_error = None
    fb.upload_fails_for = {"atmega328"}  # old-bootloader board
    assert not fb.upload(tmp_path, "arduino:avr:nano:cpu=atmega328", "/dev/ttyFAKE0", tmp_path).ok
    assert fb.upload(tmp_path, "arduino:avr:nano:cpu=atmega328old", "/dev/ttyFAKE0", tmp_path).ok
    fb.unplugged = True
    assert fb.list_ports() == []


def test_fake_board_enforces_arduino_cli_sketch_naming(tmp_path: Path):
    """arduino-cli: the main .ino must be named after its directory (found on the Pi)."""
    fb = FakeBoard()
    bad = tmp_path / "0001"
    bad.mkdir()
    (bad / "other.ino").write_text("")
    r = fb.compile(bad, "arduino:avr:nano:cpu=atmega328", tmp_path / "o")
    assert not r.ok and "main file missing" in r.log
    good = tmp_path / "blink"
    good.mkdir()
    (good / "blink.ino").write_text("")
    assert fb.compile(good, "arduino:avr:nano:cpu=atmega328", tmp_path / "o2").ok
