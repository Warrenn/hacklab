"""P8 round 2 step 3: the AI helper explains the code (whole sketch or a line range) for a
kid: story, steps for a picture, a metaphor. Cached per version, logged, guarded."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from hacklab.app import create_app
from hacklab.config import Config
from hacklab.genie import ExplainResult, FakeGenieClient, Genie
from hacklab.guard import check_text
from hacklab.profiles import load_boxes
from tests.test_ask_runner import make, wait_done

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


EXPLANATION = {
    "title": "The turret listens, then moves",
    "story": [
        "Think of the turret as a dog waiting for a whistle.",
        "The remote is the whistle: every key is a different note.",
    ],
    "steps": [
        {"label": "Listen", "detail": "The IR eye waits for a key."},
        {"label": "Decide", "detail": "The switch picks the matching action."},
        {"label": "Move", "detail": "A servo turns for a short moment."},
    ],
    "metaphor": "The servo is like a tap you open for a second, then close.",
    "watch_for": "Press 7 and count the shakes.",
}


def test_explain_result_shape():
    r = ExplainResult(**EXPLANATION)
    assert r.title and len(r.story) == 2 and len(r.steps) == 3 and r.metaphor


def test_genie_explain_uses_the_teaching_prompt_and_the_code(boxes_dir):
    box = load_boxes(boxes_dir)["testbox"]
    client = FakeGenieClient([EXPLANATION])
    genie = Genie(client, "claude-test", box, "void loop() {}")
    result, usage = genie.explain("int a = 1;\nvoid loop() { a++; }\n", lines=(2, 2))
    assert isinstance(result, ExplainResult) and result.title
    call = client.calls[0]
    system = call["system"][0]["text"]
    assert "story" in system.lower() and "11-year-old" in system
    assert "Test Box" in system  # the hardware notes travel along
    user = call["messages"][-1]["content"]
    assert "void loop() { a++; }" in user and "lines 2 to 2" in user
    assert call["output_format"] is ExplainResult


def test_check_text_catches_links_emoji_and_leaks_in_any_text():
    bad = check_text({"story": "see https://x.y 🚀 Rules you never break"})
    assert any("link" in p for p in bad) and any("emoji" in p for p in bad)
    assert any("instructions" in p for p in bad)
    assert check_text({"story": "A servo is like a tap."}) == []


async def test_explain_job_returns_the_explanation_and_caches_it(tmp_path, boxes_dir):
    fb, store, runner, client = make(tmp_path, boxes_dir, [EXPLANATION, EXPLANATION])
    job = await wait_done(runner, await runner.submit("explain", {"box": "testbox", "scope": "sketch"}))
    assert job.state == "done" and job.explanation["title"] == EXPLANATION["title"]
    assert fb.uploads == 0 and len(client.calls) == 1
    # same version, same scope: served from the cache, no second API call
    again = await wait_done(runner, await runner.submit("explain", {"box": "testbox", "scope": "sketch"}))
    assert again.explanation == job.explanation and len(client.calls) == 1
    cached = store.version_dir("testbox", store.current("testbox")) / "explain-sketch.json"
    assert json.loads(cached.read_text())["title"] == EXPLANATION["title"]
    # a different range is a different explanation
    lines = await wait_done(
        runner, await runner.submit("explain", {"box": "testbox", "scope": "lines", "from": 2, "to": 3})
    )
    assert lines.state == "done" and len(client.calls) == 2


async def test_explain_job_declines_a_bad_explanation(tmp_path, boxes_dir):
    bad = {**EXPLANATION, "story": ["Watch https://example.com for more."]}
    fb, store, runner, client = make(tmp_path, boxes_dir, [bad])
    job = await wait_done(runner, await runner.submit("explain", {"box": "testbox", "scope": "sketch"}))
    assert job.state == "failed" and "Pick a trick" in job.message_kid


def test_api_explain_validates_and_the_mock_backend_answers(tmp_path, boxes_dir):
    cfg = Config(data_dir=tmp_path / "data", fake_board=True, boxes_dir=boxes_dir)
    with TestClient(create_app(cfg)) as c:
        assert c.post("/api/explain", json={"scope": "sketch"}).status_code == 409  # no box yet
        c.post("/api/box", json={"id": "testbox"})
        assert c.post("/api/explain", json={"scope": "lines", "from": 5, "to": 2}).status_code == 422
        assert c.post("/api/explain", json={"scope": "what"}).status_code == 422
        job_id = c.post("/api/explain", json={"scope": "lines", "from": 2, "to": 4}).json()["job_id"]
        for _ in range(200):
            j = c.get(f"/api/jobs/{job_id}").json()
            if j["state"] in ("done", "failed"):
                break
            asyncio.run(asyncio.sleep(0.02))
        assert j["state"] == "done" and j["kind"] == "explain"
        assert j["explanation"]["title"] and j["explanation"]["steps"]
        assert c.get("/api/status").json()["versions_count"] == 1  # nothing flashed
