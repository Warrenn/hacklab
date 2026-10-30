"""API: ai_available, /api/ask with the genie, cap and away handling."""

import time

from fastapi.testclient import TestClient

from hacklab.app import create_app
from hacklab.board import FakeBoard
from hacklab.config import Config
from hacklab.genie import FakeGenieClient
from hacklab.jobs import TERMINAL_STATES
from hacklab.spend import SpendLedger
from tests.test_genie import golden


def make(tmp_path, boxes_dir, responses, api_key="k", cap=10.0):
    cfg = Config(
        data_dir=tmp_path / "data",
        fake_board=False,
        boxes_dir=boxes_dir,
        api_key=api_key,
        monthly_cap_usd=cap,
    )
    return TestClient(create_app(cfg, board=FakeBoard(), genie_client=FakeGenieClient(responses)))


def settle(client, job_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["state"] in TERMINAL_STATES:
            return j
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_ask_end_to_end_with_prompts(tmp_path, boxes_dir):
    with make(tmp_path, boxes_dir, golden("shake-head-on-7")) as c:
        assert c.get("/api/status").json()["ai_available"] is True
        c.post("/api/box", json={"id": "testbox"})
        j = settle(c, c.post("/api/ask", json={"text": "shake on 7"}).json()["job_id"])
        assert j["state"] == "done" and j["prompts"]
        assert c.get("/api/status").json()["current_version"] == "0001"
        assert "cmd7" in c.get("/api/sketch/current").json()["source"]


def test_no_key_means_helper_away(tmp_path, boxes_dir):
    with make(tmp_path, boxes_dir, [], api_key=None) as c:
        assert c.get("/api/status").json()["ai_available"] is False
        c.post("/api/box", json={"id": "testbox"})
        r = c.post("/api/ask", json={"text": "x"})
        assert r.status_code == 409 and "away" in r.json()["detail"]


def test_cap_reached_disables_the_helper(tmp_path, boxes_dir):
    from types import SimpleNamespace

    SpendLedger(tmp_path / "data").record(
        "claude-sonnet-5-5",
        SimpleNamespace(
            input_tokens=10_000_000,
            output_tokens=0,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )
    with make(tmp_path, boxes_dir, golden("shake-head-on-7"), cap=5.0) as c:
        assert c.get("/api/status").json()["ai_available"] is False
        c.post("/api/box", json={"id": "testbox"})
        assert c.post("/api/ask", json={"text": "x"}).status_code == 409


def test_every_ask_is_logged_and_charged(tmp_path, boxes_dir):
    with make(tmp_path, boxes_dir, golden("fire-when-3-pressed")) as c:
        c.post("/api/box", json={"id": "testbox"})
        settle(c, c.post("/api/ask", json={"text": "fire on 3"}).json()["job_id"])
    assert SpendLedger(tmp_path / "data").month_total() > 0
    log = (tmp_path / "data" / "testbox" / "logs" / "asks.jsonl").read_text()
    assert '"fire on 3"' in log and '"kind": "sketch"' in log


def test_box_without_skeleton_reports_helper_away(tmp_path, boxes_dir):
    from tests.conftest import write_box

    write_box(boxes_dir, "devbox", stock_location="device")
    with make(tmp_path, boxes_dir, golden("fire-when-3-pressed")) as c:
        d = tmp_path / "data" / "boxes" / "devbox" / "stock" / "stock"
        d.mkdir(parents=True)
        (d / "stock.ino").write_text("void setup(){} void loop(){}")
        c.post("/api/box", json={"id": "devbox"})
        assert c.get("/api/status").json()["ai_available"] is False
        assert c.post("/api/ask", json={"text": "x"}).status_code == 409
