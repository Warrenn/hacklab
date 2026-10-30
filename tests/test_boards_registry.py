"""provisioning/boards.toml -> BoardSpec: what a box's fqbn means for detection and upload."""

import tomllib
from pathlib import Path

import pytest

from hacklab.board import BoardSpec, Port, board_spec, find_board, load_registry

ROOT = Path(__file__).resolve().parent.parent


def test_registry_loads_the_nano_and_esp32_specs():
    reg = load_registry()
    nano, esp = reg["arduino:avr:nano"], reg["esp32:esp32:esp32"]
    assert nano.core == "arduino:avr" and nano.cpu_options == ("atmega328", "atmega328old")
    assert ("0x1a86", "0x7523") in nano.usb_ids and nano.reenumerates is False and nano.verified
    assert nano.fqbns() == ["arduino:avr:nano:cpu=atmega328", "arduino:avr:nano:cpu=atmega328old"]
    assert esp.core == "esp32:esp32" and esp.cpu_options == ()
    assert esp.fqbns() == ["esp32:esp32:esp32"]
    assert esp.reenumerates is True and esp.verified is False  # no board on hand yet
    assert ("0x303a", "0x1001") in esp.usb_ids


def test_registry_lists_extra_core_index_urls():
    reg = load_registry()
    assert any("package_esp32_index.json" in u for u in reg.additional_urls)


def test_every_profile_fqbn_is_in_the_registry():
    reg = load_registry()
    for prof in (ROOT / "boxes").glob("*/profile.toml"):
        fqbn = tomllib.loads(prof.read_text())["board"]["fqbn"]
        assert fqbn in reg, f"{prof}: {fqbn} not in provisioning/boards.toml"


def test_board_spec_unknown_fqbn_names_the_known_ones():
    with pytest.raises(KeyError, match="arduino:avr:nano"):
        board_spec("teensy:avr:teensy41")


def test_registry_validation(tmp_path: Path):
    bad = tmp_path / "boards.toml"
    bad.write_text('[boards."x:y:z"]\ncore = "x:y"\nusb_ids = ["nothex"]\n')
    with pytest.raises(ValueError, match="usb_ids"):
        load_registry(bad)
    bad.write_text('[boards."x:y:z"]\nusb_ids = ["1a86:7523"]\n')
    with pytest.raises(ValueError, match="core"):
        load_registry(bad)


def test_find_board_uses_the_spec_usb_ids():
    ports = [
        Port("/dev/ttyACM0", "0x303a", "0x1001", "ESP32-S3-ABC"),
        Port("/dev/ttyUSB0", "0x1a86", "0x7523", ""),
    ]
    nano, esp = board_spec("arduino:avr:nano"), board_spec("esp32:esp32:esp32")
    assert find_board(ports, nano).address == "/dev/ttyUSB0"
    assert find_board(ports[:1], nano) is None  # a native-USB ESP32 is not a Nano
    assert find_board(ports, esp).address == "/dev/ttyACM0"
    assert find_board(ports).address == "/dev/ttyUSB0"  # default: Nano, as before


def test_spec_is_hashable_and_frozen():
    s = board_spec("arduino:avr:nano")
    assert isinstance(s, BoardSpec) and hash(s)
    with pytest.raises(AttributeError):
        s.core = "x"  # type: ignore[misc]
