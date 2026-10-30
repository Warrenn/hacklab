import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from hacklab.app import create_app, format_sse
from hacklab.config import Config
from hacklab.jobs import TERMINAL_STATES, FakeJobRunner


@pytest.fixture
def client(boxes_dir):
    cfg = Config(fake_board=True, boxes_dir=boxes_dir)
    app = create_app(config=cfg, runner=FakeJobRunner(delay=0))
    with TestClient(app) as c:
        yield c


def wait_job(client: TestClient, job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] in TERMINAL_STATES:
            return job
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} never finished: {job}")


def test_status_before_box_selected(client):
    s = client.get("/api/status").json()
    assert s["box"] is None
    assert s["online"] is True
    assert s["ai_available"] is False  # no ANTHROPIC_API_KEY
    assert s["board_connected"] is True  # fake board
    assert s["versions_count"] == 0


def test_boxes_come_from_profiles(client):
    ids = {b["id"] for b in client.get("/api/boxes").json()}
    assert ids == {"testbox"}
    for b in client.get("/api/boxes").json():
        assert set(b) == {"id", "name", "picture"}


def test_select_box(client):
    assert client.post("/api/box", json={"id": "nope"}).status_code == 404
    assert client.post("/api/box", json={"id": "testbox"}).status_code == 200
    s = client.get("/api/status").json()
    assert s["box"] == "testbox"
    assert s["versions_count"] == 1
    assert s["current_version"]


def test_everything_box_scoped_refuses_without_a_box(client):
    assert client.get("/api/behaviours").status_code == 409
    assert client.post("/api/flash/behaviour", json={"id": "x"}).status_code == 409
    assert (
        client.post("/api/flash/template", json={"template_id": "x", "values": {}}).status_code
        == 409
    )
    assert client.post("/api/flash/sketch", json={"source": "void loop(){}"}).status_code == 409
    assert client.post("/api/ask", json={"text": "hi"}).status_code == 409
    assert client.post("/api/undo").status_code == 409
    assert client.post("/api/reset").status_code == 409
    assert client.get("/api/sketch/current").status_code == 409


def test_behaviours_have_kid_fields_and_tweakables(client):
    client.post("/api/box", json={"id": "testbox"})
    bs = client.get("/api/behaviours").json()
    assert len(bs) >= 1
    for b in bs:
        assert set(b) == {"id", "title", "description", "tweakables"}
        assert "http" not in b["description"]
    assert any(b["tweakables"] for b in bs)
    tw = next(b["tweakables"] for b in bs if b["tweakables"])[0]
    assert {"name", "value", "range", "step"} <= set(tw)


def test_flash_behaviour_walks_to_done_and_adds_a_version(client):
    client.post("/api/box", json={"id": "testbox"})
    assert client.post("/api/flash/behaviour", json={"id": "nope"}).status_code == 404
    r = client.post("/api/flash/behaviour", json={"id": "shake"})
    assert r.status_code == 200
    job = wait_job(client, r.json()["job_id"])
    assert job["state"] == "done"
    assert job["message_kid"]
    assert job["sketch_ref"]
    assert client.get("/api/status").json()["versions_count"] == 2


def test_ask_walks_through_thinking_and_offers_prompts(client):
    client.post("/api/box", json={"id": "testbox"})
    assert client.post("/api/ask", json={"text": ""}).status_code == 422
    r = client.post("/api/ask", json={"text": "make it shake its head when I press 7"})
    job = wait_job(client, r.json()["job_id"])
    assert job["state"] == "done"
    assert job["prompts"] == []  # P4 adds curiosity prompts


def test_ask_can_fail_in_kid_language(client):
    client.post("/api/box", json={"id": "testbox"})
    r = client.post("/api/ask", json={"text": "fail on purpose"})
    job = wait_job(client, r.json()["job_id"])
    assert job["state"] == "failed"
    assert job["message_kid"]
    assert "Traceback" not in job["message_kid"]
    assert client.get("/api/status").json()["versions_count"] == 1


def test_undo_and_reset(client):
    client.post("/api/box", json={"id": "testbox"})
    assert client.post("/api/undo").status_code == 409  # nothing to undo yet
    for _ in range(2):
        wait_job(client, client.post("/api/flash/behaviour", json={"id": "shake"}).json()["job_id"])
    assert client.get("/api/status").json()["versions_count"] == 3
    wait_job(client, client.post("/api/undo").json()["job_id"])
    assert client.get("/api/status").json()["versions_count"] == 2
    wait_job(client, client.post("/api/reset").json()["job_id"])
    s = client.get("/api/status").json()
    assert s["versions_count"] == 1
    assert s["current_version"] == "stock"


def test_sketch_current_is_the_profile_stock_sketch(client):
    client.post("/api/box", json={"id": "testbox"})
    s = client.get("/api/sketch/current").json()
    assert s["box"] == "testbox"
    assert s["version"] == "stock"
    assert s["source"] == "void setup(){} void loop(){}\n"


def test_concepts(client):
    assert client.get("/api/concepts/servo").status_code == 409  # pick a box first
    client.post("/api/box", json={"id": "testbox"})
    assert client.get("/api/concepts/nope").status_code == 404
    c = client.get("/api/concepts/servo").json()
    assert set(c) == {"id", "title", "explanation"}
    assert "http" not in c["explanation"]


def test_event_feed_reports_job_progress():
    # Starlette's TestClient buffers whole responses, so the open-ended SSE
    # route is covered end to end by the P3 browser tests; here we test the
    # feed the route reads from, and the SSE framing it emits.
    async def run():
        runner = FakeJobRunner(delay=0)
        q = runner.subscribe()
        job_id = await runner.submit("flash", {})
        states = []
        while True:
            ev = await asyncio.wait_for(q.get(), 1)
            if ev["job_id"] == job_id:
                states.append(ev["state"])
                if ev["state"] in TERMINAL_STATES:
                    return states

    states = asyncio.run(run())
    assert states[-1] == "done"
    assert "uploading" in states


def test_sse_framing():
    assert format_sse({"a": 1}) == 'data: {"a": 1}\n\n'
