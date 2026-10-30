"""Skeleton assembly: fragments replace the //@@ markers, indentation kept."""

import json
from pathlib import Path

import pytest

from hacklab.profiles import load_boxes
from hacklab.skeleton import Fragments, SkeletonError, assemble, load_skeleton
from tests.conftest import SKELETON


def test_assemble_replaces_every_marker_with_indentation():
    f = Fragments(
        params="int n = 2;",
        cases="case 2: wave(n); break;",
        loop="delay(1);",
        functions="void x() {}",
    )
    out = assemble(SKELETON, f)
    assert "//@@" not in out
    assert "\nint n = 2;\n" in out
    assert "\n        case 2: wave(n); break;\n" in out  # indented like the marker
    assert "\n    delay(1);\n" in out and "\nvoid x() {}\n" in out


def test_empty_fragments_leave_a_blank_line_and_multiline_fragments_indent_each_line():
    out = assemble(SKELETON, Fragments(cases="case 2:\n  wave(2);\n  break;"))
    assert "        case 2:\n          wave(2);\n          break;" in out
    assert "//@@" not in out


def test_missing_marker_is_an_error():
    with pytest.raises(SkeletonError, match="LOOP"):
        assemble("void loop() {}\n//@@PARAMS\n//@@CASES\n//@@FUNCTIONS\n", Fragments())


def test_fragments_round_trip_json():
    f = Fragments(params="a", cases="b", loop="c", functions="d")
    assert Fragments.from_dict(json.loads(json.dumps(f.to_dict()))) == f
    assert Fragments.from_dict({}) == Fragments()


def test_load_skeleton_from_repo_and_device(boxes_dir: Path, tmp_path: Path):
    box = load_boxes(boxes_dir)["testbox"]
    assert "//@@CASES" in load_skeleton(box, tmp_path / "data")
    from tests.conftest import write_box

    write_box(boxes_dir, "devbox", stock_location="device")
    dev = load_boxes(boxes_dir)["devbox"]
    assert load_skeleton(dev, tmp_path / "data") is None  # not on the device yet
    d = tmp_path / "data" / "boxes" / "devbox" / "genie"
    d.mkdir(parents=True)
    (d / "skeleton.ino").write_text(SKELETON)
    assert load_skeleton(dev, tmp_path / "data") == SKELETON


def test_real_turret_skeleton_assembles_the_golden():
    box = load_boxes(Path(__file__).resolve().parent.parent / "boxes")["ir-turret"]
    sk = load_skeleton(box, Path("/nonexistent"))
    g = json.loads((Path(__file__).parent / "golden" / "shake-head-on-7.json").read_text())[
        "responses"
    ][0]
    out = assemble(sk, Fragments.from_dict(g))
    assert "int shakes = 3;" in out and out.index("int shakes") < out.index("int yawMoveSpeed")
    assert "case cmd7: shakeNo(shakes); break;" in out
    assert (
        out.index("switch(IrReceiver")
        < out.index("case cmd7")
        < out.index("#pragma endregion LOOP")
    )
    assert "//@@" not in out
