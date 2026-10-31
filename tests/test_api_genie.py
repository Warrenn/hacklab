"""API: ai_available, /api/ask with the genie, and away handling (the spend budget lives
only in the Claude Console; a refused API call puts the helper away)."""

import time

from fastapi.testclient import TestClient

from hacklab.app import create_app
from hacklab.board import FakeBoard
from hacklab.config import Config
from hacklab.genie import FakeGenieClient
from hacklab.jobs import TERMINAL_STATES
from hacklab.spend import SpendLedger
from tests.test_genie import golden


def make(tmp_path, boxes_dir, responses, api_key="k"):
    cfg = Config(
        data_dir=tmp_path / "data",
        fake_board=False,
        boxes_dir=boxes_dir,
        api_key=api_key,
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
        assert j["state"] == "done" and isinstance(j["prompts"], list)
        assert c.get("/api/status").json()["current_version"] == "0001"
        assert "cmd7" in c.get("/api/sketch/current").json()["source"]


def test_no_key_means_helper_away(tmp_path, boxes_dir):
    with make(tmp_path, boxes_dir, [], api_key=None) as c:
        assert c.get("/api/status").json()["ai_available"] is False
        c.post("/api/box", json={"id": "testbox"})
        r = c.post("/api/ask", json={"text": "x"})
        assert r.status_code == 409 and "away" in r.json()["detail"]


def test_console_spend_limit_error_puts_the_helper_away(tmp_path, boxes_dir):
    # The Console limit is the only budget: the API refuses (400 invalid_request_error),
    # the ask fails with the "away" message and the helper reports away afterwards.
    refused = [{"error": "400 invalid_request_error: usage limit reached"}]
    with make(tmp_path, boxes_dir, refused) as c:
        c.post("/api/box", json={"id": "testbox"})
        assert c.get("/api/status").json()["ai_available"] is True
        job = settle(c, c.post("/api/ask", json={"text": "x"}).json()["job_id"])
        assert job["state"] == "failed"
        assert "away" in job["message_kid"].lower()
        assert c.get("/api/status").json()["ai_available"] is False
        assert c.post("/api/ask", json={"text": "x"}).status_code == 409


def test_config_has_no_cap_of_its_own():
    assert not hasattr(Config(), "monthly_cap_usd")


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
