"""Hack Pack IDE importer: dump -> box profile (P6 unit B)."""

import json
import shutil
from pathlib import Path

import pytest

from hacklab.importer import import_box, is_mit, place_markers
from hacklab.profiles import load_box

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).parent / "fixtures" / "ide"


def dump(name: str) -> dict:
    return json.loads((FIX / f"{name}.json").read_text())


@pytest.fixture
def boxes(tmp_path: Path) -> Path:
    b = tmp_path / "boxes"
    b.mkdir()
    shutil.copytree(ROOT / "boxes" / "_template", b / "_template")
    return b


def test_mit_detection():
    files = dump("ir-turret")["files"]
    assert is_mit(files["stock/stock.ino"]) and is_mit(files["passcode/passcode.ino"])
    assert not is_mit(dump("synth-box")["files"]["StockCode/StockCode.ino"])


def test_turret_lands_in_the_repo_with_a_full_profile(boxes: Path, tmp_path: Path):
    rep = import_box(dump("ir-turret"), boxes, tmp_path / "staging")
    box = boxes / "ir-turret"
    assert (box / "stock" / "stock" / "stock.ino").read_text() == dump("ir-turret")["files"][
        "stock/stock.ino"
    ]
    assert (box / "stock" / "passcode" / "passcode.ino").is_file()
    assert rep.license == {"stock": "MIT", "passcode": "MIT"}
    prof = (box / "profile.toml").read_text()
    assert 'id = "ir-turret"' in prof and 'location = "repo"' in prof and 'main = "stock"' in prof
    assert 'fqbn = "arduino:avr:nano"' in prof
    pins = (box / "pins.toml").read_text()
    assert "[pins]" in pins  # no #define pins in the turret sketch (servos attach by number)
    assert "yawMoveSpeed" in pins  # markers listed as limits
    hw = (box / "hardware.md").read_text()
    assert "TODO" in hw
    sk = (box / "genie" / "skeleton.ino").read_text()
    for m in ("//@@PARAMS", "//@@LOOP", "//@@CASES", "//@@FUNCTIONS"):
        assert sk.count(m) == 1, m
    assert sk.index("//@@PARAMS") < sk.index("void setup()")
    assert sk.index("void loop()") < sk.index("//@@LOOP") < sk.index("switch(IrReceiver")
    assert sk.index("case up:") < sk.index("//@@CASES") < sk.index("#pragma endregion LOOP")
    assert sk.index("//@@FUNCTIONS") < sk.index("#pragma endregion FUNCTIONS")
    loaded = load_box(box)  # the result is a valid profile
    assert loaded.stock_location == "repo" and loaded.genie["skeleton"] == "genie/skeleton.ino"
    assert not (tmp_path / "staging").exists()


def test_unlicensed_box_is_staged_for_the_device(boxes: Path, tmp_path: Path):
    rep = import_box(dump("synth-box"), boxes, tmp_path / "staging", fqbn="arduino:avr:nano")
    box = boxes / "synth-box"
    assert not (box / "stock").exists()
    staged = tmp_path / "staging" / "synth-box" / "stock" / "StockCode"
    assert (staged / "StockCode.ino").is_file() and (staged / "config.h").is_file()
    assert rep.license == {"StockCode": "none"}
    prof = (box / "profile.toml").read_text()
    assert 'location = "device"' in prof and 'main = "StockCode"' in prof
    pins = (box / "pins.toml").read_text()
    assert "rf_s1_v = 19" in pins and "lift_pwm = 3" in pins
    assert "maxspeed" in pins.lower()  # config.h marker reported as a limit
    hw = (box / "hardware.md").read_text()
    assert "| LIFT_PWM | 3 |" in hw
    # the skeleton is staged next to the stock (device location), not in the repo
    sk = (tmp_path / "staging" / "synth-box" / "genie" / "skeleton.ino").read_text()
    assert not (box / "genie").exists()
    assert (
        sk.index("unsigned long lastStrafe = 0;")
        < sk.index("//@@PARAMS")
        < sk.index("void setup()")
    )
    assert (
        sk.index("void loop()")
        < sk.index("//@@LOOP")
        < sk.index("//@@CASES")
        < sk.index("getDirection();")
    )
    assert sk.rstrip().endswith("//@@FUNCTIONS")
    load_box(box)


def test_second_run_keeps_hand_edited_files(boxes: Path, tmp_path: Path):
    import_box(dump("ir-turret"), boxes, tmp_path / "staging")
    hw = boxes / "ir-turret" / "hardware.md"
    hw.write_text("# hand written\n")
    rep = import_box(dump("ir-turret"), boxes, tmp_path / "staging")
    assert hw.read_text() == "# hand written\n"
    assert "ir-turret/hardware.md" in rep.kept and "ir-turret/profile.toml" in rep.kept
    assert "ir-turret/stock/stock/stock.ino" in rep.written  # stock is always refreshed verbatim


def test_place_markers_shapes():
    turret = dump("ir-turret")["files"]["stock/stock.ino"]
    assert "//@@CASES\n        }" in place_markers(turret).replace("\r", "")
    plain = "int a = 1;\nvoid setup() {}\nvoid loop() {\n  a++;\n}\nvoid f() {}\n"
    out = place_markers(plain)
    expected = (
        "int a = 1;\n//@@PARAMS\nvoid setup() {}\nvoid loop() {\n  //@@LOOP\n  //@@CASES\n"
        "  a++;\n}\nvoid f() {}\n//@@FUNCTIONS\n"
    )
    assert out == expected


def test_bad_dump_is_rejected(boxes: Path, tmp_path: Path):
    with pytest.raises(ValueError):
        import_box({"slug": "Bad Slug!", "files": {}}, boxes, tmp_path / "s")
    with pytest.raises(ValueError):
        import_box(
            {"slug": "nothing", "files": {"x/readme.txt": "no sketch here"}}, boxes, tmp_path / "s"
        )
