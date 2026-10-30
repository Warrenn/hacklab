"""Every shipped sketch compiles for its board. Needs a toolchain: set
HACKLAB_CLI=/opt/hacklab/bin/arduino-cli (and HACKLAB_CLI_CONFIG). Runs in the
Docker CI job and on the Pi; skipped elsewhere."""

import os
from pathlib import Path

import pytest

from hacklab.board import ArduinoCli
from hacklab.profiles import load_boxes

CLI = os.environ.get("HACKLAB_CLI")
pytestmark = pytest.mark.skipif(not CLI, reason="HACKLAB_CLI not set")

BOXES = load_boxes(Path(__file__).resolve().parent.parent / "boxes")
SKETCHES = [
    (box.id, kind, item.id, item.sketch_dir)
    for box in BOXES.values()
    for kind, items in (("behaviour", box.behaviours), ("template", box.templates))
    for item in items.values()
] + [
    (box.id, "stock", d.name, d)
    for box in BOXES.values()
    if box.stock_location == "repo"
    for d in sorted((box.root / "stock").iterdir())
    if d.is_dir()
]


@pytest.mark.parametrize(
    "box_id, kind, item_id, sketch_dir",
    SKETCHES,
    ids=lambda v: str(v) if isinstance(v, str) else "",
)
def test_sketch_compiles(box_id, kind, item_id, sketch_dir, tmp_path):
    cli = ArduinoCli(CLI, os.environ.get("HACKLAB_CLI_CONFIG"))
    res = cli.compile(sketch_dir, BOXES[box_id].fqbn, tmp_path)
    assert res.ok, res.log[-2000:]
