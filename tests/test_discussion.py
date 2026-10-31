"""P8 round 2: when the AI helper answers with a question, the kid can reply; the reply
carries the earlier turns so the model has the context."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from hacklab.app import create_app
from hacklab.board import FakeBoard
from hacklab.config import Config
from hacklab.genie import FakeGenieClient
from tests.test_ask_runner import make, wait_done
from tests.test_genie import golden

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_ask_body_accepts_a_short_history(tmp_path, boxes_dir):
    cfg = Config(data_dir=tmp_path / "data", fake_board=True, boxes_dir=boxes_dir)
    with TestClient(create_app(cfg)) as c:
        c.post("/api/box", json={"id": "testbox"})
        hist = [{"role": "kid", "text": "make it move"}, {"role": "helper", "text": "Which key?"}]
        assert c.post("/api/ask", json={"text": "key 5", "history": hist}).status_code == 200
        too_many = [{"role": "kid", "text": "x"}] * 11
        assert c.post("/api/ask", json={"text": "key 5", "history": too_many}).status_code == 422
        bad_role = [{"role": "robot", "text": "x"}]
        assert c.post("/api/ask", json={"text": "key 5", "history": bad_role}).status_code == 422


async def test_clarify_answer_ends_the_job_without_flashing_and_says_so(tmp_path, boxes_dir):
    fb, store, runner, client = make(tmp_path, boxes_dir, golden("clarify-which-key"))
    job = await wait_done(
        runner, await runner.submit("ask", {"box": "testbox", "text": "make it move"})
    )
    assert job.state == "done" and job.answer == "clarify"
    assert "Which key" in job.message_kid and fb.uploads == 0
    assert job.to_dict()["answer"] == "clarify"


async def test_reply_sends_the_earlier_turns_to_the_model(tmp_path, boxes_dir):
    fb, store, runner, client = make(tmp_path, boxes_dir, golden("shake-head-on-7"))
    hist = [{"role": "kid", "text": "make it move"}, {"role": "helper", "text": "Which key?"}]
    job = await wait_done(
        runner, await runner.submit("ask", {"box": "testbox", "text": "key 7", "history": hist})
    )
    assert job.state == "done" and job.answer == "sketch" and fb.uploads == 1
    msgs = client.calls[0]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert "make it move" in msgs[0]["content"] and msgs[1]["content"] == "Which key?"
    assert "key 7" in msgs[2]["content"]


def test_mock_runner_answers_which_questions_with_a_question(tmp_path, boxes_dir):
    cfg = Config(data_dir=tmp_path / "data", fake_board=True, boxes_dir=boxes_dir)
    with TestClient(create_app(cfg)) as c:
        c.post("/api/box", json={"id": "testbox"})
        job_id = c.post("/api/ask", json={"text": "which key makes it dance"}).json()["job_id"]
        for _ in range(200):
            j = c.get(f"/api/jobs/{job_id}").json()
            if j["state"] in ("done", "failed"):
                break
            asyncio.run(asyncio.sleep(0.02))
        assert j["state"] == "done" and j["answer"] == "clarify"
        assert "Which key" in j["message_kid"]
        assert c.get("/api/status").json()["versions_count"] == 1  # nothing flashed


def test_fake_board_untouched_by_a_clarify(tmp_path, boxes_dir):
    fb = FakeBoard()
    assert fb.uploads == 0 and isinstance(FakeGenieClient([]), FakeGenieClient)
