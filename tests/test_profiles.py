"""Box profile loader + validator."""

from pathlib import Path

import pytest

from hacklab.profiles import ProfileError, load_boxes
from tests.conftest import write_box


def test_loads_box_with_behaviours_templates_concepts(boxes_dir: Path):
    boxes = load_boxes(boxes_dir)
    b = boxes["testbox"]
    assert b.name == "Test Box" and b.fqbn == "arduino:avr:nano"
    assert b.libraries == ["Servo@1.3.0"]
    assert b.pins == {"servo": 10} and b.limits["angle"] == {"min": 0, "max": 180}
    assert "One servo" in b.hardware_md
    assert list(b.behaviours) == ["shake"] and list(b.templates) == ["wave"]
    sh = b.behaviours["shake"]
    assert sh.title == "Shake" and sh.kind == "behaviour" and sh.concepts == ["servo"]
    assert [t.name for t in sh.tweakables] == ["shakes", "speed", "fast"]
    assert (sh.sketch_dir / "shake.ino").is_file()
    assert b.concepts["servo"].title == "What is a servo?"


def test_behaviour_api_shape(boxes_dir: Path):
    b = load_boxes(boxes_dir)["testbox"]
    api = b.behaviours["shake"].to_api()
    assert api["id"] == "shake" and api["title"] == "Shake"
    assert api["tweakables"][0] == {"name": "shakes", "value": 3, "range": [1, 10], "step": 1}
    assert api["tweakables"][2] == {"name": "fast", "value": False, "options": ["true", "false"]}


def test_stock_dir_repo_vs_device(tmp_path: Path):
    root = tmp_path / "boxes"
    write_box(root, "repo-box")
    write_box(root, "dev-box", stock_location="device")
    boxes = load_boxes(root)
    assert boxes["repo-box"].stock_dir(tmp_path / "data") == root / "repo-box" / "stock" / "stock"
    assert (
        boxes["dev-box"].stock_dir(tmp_path / "data")
        == tmp_path / "data" / "boxes" / "dev-box" / "stock" / "stock"
    )


def test_to_api_box_entry(boxes_dir: Path):
    assert load_boxes(boxes_dir)["testbox"].to_api() == {
        "id": "testbox",
        "name": "Test Box",
        "picture": "/static/boxes/testbox.svg",
    }


@pytest.mark.parametrize(
    "mutate, match",
    [
        (lambda b: (b / "pins.toml").write_text("[pins]\nservo = 99\n"), "pin"),
        (lambda b: (b / "behaviours" / "shake" / "shake.ino").unlink(), "shake.ino"),
        (lambda b: (b / "behaviours" / "shake.toml").write_text('id = "shake"\n'), "title"),
        (lambda b: (b / "profile.toml").write_text('id = "other"\nname = "x"\n'), "id"),
        (lambda b: (b / "concepts.toml").unlink(), "concepts.toml"),
        (
            lambda b: (b / "behaviours" / "shake" / "shake.ino").write_text(
                'int x = 1; ///{"range":[1,}\n'
            ),
            "marker",
        ),
    ],
)
def test_validation_errors_name_the_problem(boxes_dir: Path, mutate, match):
    mutate(boxes_dir / "testbox")
    with pytest.raises(ProfileError, match=match):
        load_boxes(boxes_dir)


def test_library_not_in_whitelist_is_an_error(boxes_dir: Path, tmp_path: Path):
    wl = tmp_path / "libraries.txt"
    wl.write_text("# whitelist\nIRremote@4.7.1\n")
    with pytest.raises(ProfileError, match="Servo"):
        load_boxes(boxes_dir, whitelist=wl)


def test_real_repo_boxes_load():
    boxes = load_boxes(Path(__file__).resolve().parent.parent / "boxes")
    assert "ir-turret" in boxes and "omnibot-forklift" in boxes
    t = boxes["ir-turret"]
    assert (
        t.stock_dir(Path("/x")).name == "stock"
        and (t.stock_dir(Path("/x")) / "stock.ino").is_file()
    )
    assert boxes["omnibot-forklift"].stock_location == "device"


def test_dotfiles_next_to_behaviours_are_ignored(boxes_dir: Path):
    """A macOS-built release once shipped AppleDouble '._x.toml' files; never parse them."""
    junk = b"\x00\x05\x16\x07\x00\xa3junk"
    (boxes_dir / "testbox" / "behaviours" / "._shake.toml").write_bytes(junk)
    (boxes_dir / "testbox" / "._profile.toml").write_bytes(b"\x00\x05\x16\x07junk")
    assert list(load_boxes(boxes_dir)["testbox"].behaviours) == ["shake"]
