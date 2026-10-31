"""P8 round 5: "What just changed?": the diff between the current version and the one before
it, a status flag that shows the chip only when there is a change, and an explanation of the
change and why that code was used."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from hacklab.app import create_app
from hacklab.board import FakeBoard
from hacklab.config import Config
from hacklab.diff import sketch_diff
from hacklab.genie import FakeGenieClient, Genie
from hacklab.jobs import TERMINAL_STATES
from hacklab.profiles import load_boxes
from tests.test_explain import EXPLANATION

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def settle(c, job_id):
    for _ in range(300):
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["state"] in TERMINAL_STATES:
            return j
        asyncio.run(asyncio.sleep(0.02))
    raise AssertionError("job did not finish")


def test_sketch_diff_covers_every_source_file(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    (a / "s.ino").write_text("int x = 1;\nvoid loop() {}\n")
    (b / "s.ino").write_text("int x = 2;\nvoid loop() { blink(); }\n")
    (a / "config.h").write_text("int top = 100;\n")
    (b / "config.h").write_text("int top = 100;\n")  # unchanged: not in the diff
    (b / "extra.h").write_text("int added = 1;\n")  # new file: in the diff
    d = sketch_diff(a, b)
    assert "-int x = 1;" in d and "+int x = 2;" in d and "+void loop() { blink(); }" in d
    assert "config.h" not in d and "+int added = 1;" in d
    assert sketch_diff(a, a) == ""


def test_sketch_diff_pairs_the_main_sketch_by_role_not_by_name(tmp_path):
    # a shipped trick's main file is nod-yes.ino, the stock's is stock.ino: the diff must be the
    # changed lines, not "stock.ino removed, nod-yes.ino added" (657 lines, seen on the Pi)
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    (a / "stock.ino").write_text("int x = 1;\nvoid loop() {}\nvoid setup() {}\n")
    (b / "nod-yes.ino").write_text("int x = 1;\nvoid loop() { nod(); }\nvoid setup() {}\n")
    d = sketch_diff(a, b)
    assert "+void loop() { nod(); }" in d and "-void loop() {}" in d
    assert "-int x = 1;" not in d and len(d.splitlines()) < 12


def test_genie_explains_a_change_with_the_diff_and_asks_why(boxes_dir):
    box = load_boxes(boxes_dir)["testbox"]
    client = FakeGenieClient([EXPLANATION])
    genie = Genie(client, "claude-test", box, "void loop() {}")
    diff = "--- a/s.ino\n+++ b/s.ino\n-int x = 1;\n+int x = 2;\n"
    genie.explain("int x = 2;\nvoid loop() {}\n", diff=diff)
    user = client.calls[0]["messages"][-1]["content"]
    assert user.lower().startswith("explain what just changed")
    assert "+int x = 2;" in user and "why" in user.lower()
    assert "int x = 2;" in user  # the current code travels along, numbered


def test_status_changed_and_the_explanation_of_the_change_real_mode(tmp_path, boxes_dir):
    cfg = Config(data_dir=tmp_path / "data", fake_board=False, boxes_dir=boxes_dir)
    with TestClient(create_app(cfg, board=FakeBoard())) as c:
        c.post("/api/box", json={"id": "testbox"})
        assert c.get("/api/status").json()["changed"] is False  # stock: nothing to compare
        assert c.post("/api/explain", json={"scope": "changed"}).status_code == 409
        settle(c, c.post("/api/flash/numbers", json={"values": {"top": 150}}).json()["job_id"])
        assert c.get("/api/status").json()["changed"] is True
        settle(c, c.post("/api/undo").json()["job_id"])
        assert c.get("/api/status").json()["changed"] is False


def test_mock_mode_flags_a_change_and_explains_it(tmp_path, boxes_dir):
    cfg = Config(data_dir=tmp_path / "data", fake_board=True, boxes_dir=boxes_dir)
    with TestClient(create_app(cfg)) as c:
        c.post("/api/box", json={"id": "testbox"})
        assert c.get("/api/status").json()["changed"] is False
        settle(c, c.post("/api/flash/behaviour", json={"id": "shake"}).json()["job_id"])
        assert c.get("/api/status").json()["changed"] is True
        j = settle(c, c.post("/api/explain", json={"scope": "changed"}).json()["job_id"])
        assert j["state"] == "done" and j["explanation"]["title"]
