"""P8 round 6: job cancel at safe points only, and one AI call at a time."""

import time

import pytest
from fastapi.testclient import TestClient

from hacklab.app import create_app
from hacklab.board import FakeBoard
from hacklab.config import Config
from hacklab.jobs import KID_BUSY, KID_STOPPED, TERMINAL_STATES
from tests.test_ask_runner import make, wait_done
from tests.test_genie import golden

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def settle(c, job_id, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["state"] in TERMINAL_STATES:
            return j
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_mock_flash_can_be_stopped_before_it_uploads(tmp_path, boxes_dir):
    cfg = Config(data_dir=tmp_path / "data", fake_board=True, boxes_dir=boxes_dir)
    with TestClient(create_app(cfg)) as c:
        c.post("/api/box", json={"id": "testbox"})
        assert c.post("/api/jobs/nope/cancel").status_code == 404
        job_id = c.post("/api/flash/behaviour", json={"id": "shake"}).json()["job_id"]
        assert c.post(f"/api/jobs/{job_id}/cancel").status_code == 200  # queued or compiling
        j = settle(c, job_id)
        assert j["state"] == "failed" and j["message_kid"] == KID_STOPPED
        assert c.get("/api/status").json()["versions_count"] == 1  # nothing written
        assert c.post(f"/api/jobs/{job_id}/cancel").status_code == 409  # already finished


async def test_real_flash_stops_before_compiling_and_before_uploading(tmp_path, boxes_dir):
    fb, store, runner, client = make(tmp_path, boxes_dir, golden("shake-head-on-7"))
    # asked to stop before it even started: nothing compiled, nothing uploaded
    job_id = await runner.submit("flash", {"box": "testbox", "id": "shake", "sketch_dir": None})
    runner.get(job_id).cancel_requested = True
    job = await wait_done(runner, job_id)
    assert job.state == "failed" and job.message_kid == KID_STOPPED and fb.uploads == 0
    # an ask whose answer arrives after the stop request: the answer is dropped, nothing flashed
    job_id = await runner.submit("ask", {"box": "testbox", "text": "shake on 7"})
    runner.get(job_id).cancel_requested = True
    job = await wait_done(runner, job_id)
    assert job.state == "failed" and job.message_kid == KID_STOPPED
    assert job.answer is None and fb.uploads == 0


def test_flasher_stops_between_compile_and_upload(tmp_path, boxes_dir):
    from hacklab.flash import Flasher

    fb = FakeBoard()
    flasher = Flasher(fb, data_dir=tmp_path / "data", reenumerate_timeout=0.2, sleep=lambda s: None)
    d = tmp_path / "sk"
    d.mkdir()
    (d / "sk.ino").write_text("void setup(){} void loop(){}")
    res = flasher.flash("testbox", d, lambda stage: None, should_stop=lambda: True)
    assert res.ok is False and res.failed_stage == "stopped" and fb.uploads == 0


def test_one_ai_call_at_a_time(tmp_path, boxes_dir):
    cfg = Config(data_dir=tmp_path / "data", fake_board=True, boxes_dir=boxes_dir)
    with TestClient(create_app(cfg)) as c:
        c.post("/api/box", json={"id": "testbox"})
        first = c.post("/api/ask", json={"text": "make it nod"})
        assert first.status_code == 200
        busy = c.post("/api/ask", json={"text": "and wave"})
        assert busy.status_code == 409 and busy.json()["detail"] == KID_BUSY
        assert c.post("/api/explain", json={"scope": "sketch"}).status_code == 409
        # a flash (no AI) is not throttled by an ask
        assert c.post("/api/flash/behaviour", json={"id": "shake"}).status_code == 200
        plan = settle(c, first.json()["job_id"])
        assert plan["answer"] == "ready"
        assert c.post("/api/ask", json={"text": "and wave"}).status_code == 200  # free again
