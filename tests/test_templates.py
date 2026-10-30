"""IDE-style ///{...} tweak markers: find, render, clamp, snap, options."""

import pytest

from hacklab.templates import TemplateError, find_tweakables, render

SRC = """\
int yawMoveSpeed = 90; // speed -- ///{"range":[10,90],"step":10}
int rollPrecision = 158; ///{"min":125,"max":225}
bool flipM4 = true; ///{"options":["true","false"]}
void loop() {
  upMove(1); ///{"range":[1,10]}
  shakeHeadNo(3); ///{"range":[1,10],"name":"shakes"}
  delay(500); // plain line, no marker
}
"""


def test_find_tweakables_names_values_and_ranges():
    tw = {t.name: t for t in find_tweakables(SRC)}
    assert set(tw) == {"yawMoveSpeed", "rollPrecision", "flipM4", "upMove", "shakes"}
    assert tw["yawMoveSpeed"].value == 90 and tw["yawMoveSpeed"].range == (10, 90)
    assert tw["yawMoveSpeed"].step == 10
    assert tw["rollPrecision"].range == (125, 225) and tw["rollPrecision"].step is None
    assert tw["flipM4"].value is True and tw["flipM4"].options == ["true", "false"]
    assert tw["upMove"].value == 1 and tw["upMove"].line == 5
    assert tw["shakes"].value == 3


def test_to_api_shape_matches_contract():
    api = [t.to_api() for t in find_tweakables(SRC)]
    assert api[0] == {"name": "yawMoveSpeed", "value": 90, "range": [10, 90], "step": 10}
    assert api[2] == {"name": "flipM4", "value": True, "options": ["true", "false"]}


def test_render_replaces_only_the_literal_on_that_line():
    out = render(SRC, {"yawMoveSpeed": 50, "upMove": 4, "shakes": 7})
    assert "int yawMoveSpeed = 50; // speed -- ///" in out
    assert "  upMove(4); ///" in out and "shakeHeadNo(7);" in out
    assert "int rollPrecision = 158;" in out  # untouched
    assert out.count("\n") == SRC.count("\n")


def test_render_clamps_and_snaps():
    out = render(SRC, {"yawMoveSpeed": 999, "rollPrecision": 1, "upMove": 7.7})
    assert "yawMoveSpeed = 90;" in out
    assert "rollPrecision = 125;" in out
    assert "upMove(8);" in out  # rounded to the integer step of the original literal


def test_render_snaps_to_step():
    assert "yawMoveSpeed = 40;" in render(SRC, {"yawMoveSpeed": 44})


def test_render_options_and_bools():
    assert "bool flipM4 = false;" in render(SRC, {"flipM4": False})
    assert "bool flipM4 = false;" in render(SRC, {"flipM4": "false"})
    with pytest.raises(TemplateError):
        render(SRC, {"flipM4": "maybe"})


def test_render_rejects_unknown_names():
    with pytest.raises(TemplateError):
        render(SRC, {"nope": 1})


def test_bad_marker_is_reported_with_line_number():
    with pytest.raises(TemplateError, match="line 1"):
        find_tweakables('int x = 1; ///{"range":[1,}\n')


def test_label_is_our_extension_and_passes_through():
    src = 'int shakes = 3; ///{"range":[1,10],"label":"How many shakes"}\nint x = 1; ///{"range":[0,1]}\n'
    api = [t.to_api() for t in find_tweakables(src)]
    assert api[0]["label"] == "How many shakes"
    assert "label" not in api[1]
