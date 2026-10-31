"""P8 round 3: an ask ends with the helper's answer (ready | clarify | explain) and never
flashes by itself; the held plan is flashed by /api/go when the kid presses Go!."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from hacklab.app import create_app
from hacklab.config import Config
from tests.test_ask_runner import make, wait_done
from tests.test_genie import golden

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_ask_holds_the_plan_and_go_flashes_it_without_a_second_model_call(
    tmp_path, boxes_dir
):
    fb, store, runner, client = make(tmp_path, boxes_dir, golden("shake-head-on-7"))
    plan = await wait_done(
        runner, await runner.submit("ask", {"box": "testbox", "text": "shake on 7"})
    )
    assert plan.state == "done" and plan.answer == "ready"
    assert plan.message_kid and "Traceback" not in plan.message_kid  # the model's own words
    assert fb.uploads == 0 and store.current("testbox").id == "0000"  # nothing flashed yet
    assert plan.to_dict()["answer"] == "ready" and "result" not in plan.to_dict()
    go = await wait_done(runner, await runner.submit("ask", {"box": "testbox", "go": plan.id}))
    assert go.state == "done" and go.answer == "sketch" and fb.uploads == 1
    assert len(client.calls) == 1  # the plan was held server-side
    cur = store.current("testbox")
    assert cur.id == "0001" and cur.note == "shake on 7"
    assert all(p["id"] in {"servo", "loop"} for p in go.prompts)


def settle(c, job_id):
    for _ in range(300):
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["state"] in ("done", "failed"):
            return j
        asyncio.run(asyncio.sleep(0.02))
    raise AssertionError("job did not finish")


def test_api_go_only_accepts_a_ready_answer_for_the_current_box(tmp_path, boxes_dir):
    cfg = Config(data_dir=tmp_path / "data", fake_board=True, boxes_dir=boxes_dir)
    with TestClient(create_app(cfg)) as c:
        assert c.post("/api/go", json={"job_id": "nope"}).status_code == 409  # no box yet
        c.post("/api/box", json={"id": "testbox"})
        assert c.post("/api/go", json={"job_id": "nope"}).status_code == 409
        q = settle(c, c.post("/api/ask", json={"text": "which key"}).json()["job_id"])
        assert q["answer"] == "clarify"
        assert c.post("/api/go", json={"job_id": q["job_id"]}).status_code == 409
        plan = settle(c, c.post("/api/ask", json={"text": "make it nod"}).json()["job_id"])
        assert plan["state"] == "done" and plan["answer"] == "ready"
        assert c.get("/api/status").json()["versions_count"] == 1
        go = settle(c, c.post("/api/go", json={"job_id": plan["job_id"]}).json()["job_id"])
        assert go["state"] == "done" and go["answer"] == "sketch" and go["kind"] == "ask"
        assert c.get("/api/status").json()["versions_count"] == 2
        # the mock failure path still fails at the flash, after Go!
        plan = settle(c, c.post("/api/ask", json={"text": "fail on purpose"}).json()["job_id"])
        assert plan["answer"] == "ready"
        go = settle(c, c.post("/api/go", json={"job_id": plan["job_id"]}).json()["job_id"])
        assert go["state"] == "failed" and "Traceback" not in go["message_kid"]
