"""RealJobRunner 'ask' jobs: genie -> assemble -> flash, retry, clarify, away."""

import asyncio
import json
from pathlib import Path

import pytest

from hacklab.board import FakeBoard, Result
from hacklab.flash import Flasher
from hacklab.genie import FakeGenieClient, Genie, GenieRefused
from hacklab.jobs import RealJobRunner
from hacklab.profiles import load_boxes
from hacklab.store import SketchStore
from tests.conftest import SKELETON

pytestmark = pytest.mark.anyio
GOLDEN = Path(__file__).parent / "golden"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def golden(name):
    return json.loads((GOLDEN / f"{name}.json").read_text())["responses"]


class StrictFakeBoard(FakeBoard):
    """Rejects a sketch containing 'fire() break' like a real compiler would."""

    def compile(self, sketch_dir, fqbn, out_dir):
        main = Path(sketch_dir) / f"{Path(sketch_dir).name}.ino"
        if main.is_file() and "fire() break" in main.read_text():
            self.compiles += 1
            return Result(False, "error: expected ';' before 'break'")
        return super().compile(sketch_dir, fqbn, out_dir)


def make(tmp_path, boxes_dir, responses, board=None):
    fb = board or StrictFakeBoard()
    box = load_boxes(boxes_dir)["testbox"]
    store = SketchStore(tmp_path / "data")
    store.ensure_baseline("testbox", box.stock_dir(tmp_path / "data"))
    flasher = Flasher(fb, data_dir=tmp_path / "data", reenumerate_timeout=0.2, sleep=lambda s: None)
    client = FakeGenieClient(responses)
    genie = Genie(client, "claude-sonnet-5-5", box, SKELETON)
    runner = RealJobRunner(flasher, store, work_dir=tmp_path / "work", genie=lambda box_id: genie)
    return fb, store, runner, client


async def wait_done(runner, job_id, timeout=5.0):
    async def _w():
        while runner.get(job_id).state not in {"done", "failed"}:
            await asyncio.sleep(0.01)

    await asyncio.wait_for(_w(), timeout)
    return runner.get(job_id)


async def test_ask_flashes_assembled_sketch_and_stores_fragments(tmp_path, boxes_dir):
    fb, store, runner, client = make(tmp_path, boxes_dir, golden("shake-head-on-7"))
    q = runner.subscribe()
    job = await wait_done(
        runner, await runner.submit("ask", {"box": "testbox", "text": "shake on 7"})
    )
    assert job.state == "done"
    assert job.message_kid and "Traceback" not in job.message_kid
    assert all(p["id"] in {"servo", "loop"} for p in job.prompts)  # filtered to the box's concepts
    assert "cmd7" in fb.last_uploaded_source and "shake" in fb.last_uploaded_source.lower()
    cur = store.current("testbox")
    assert cur.id == "0001" and cur.kind == "ask" and cur.note == "shake on 7"
    frags = json.loads((store.path("testbox", cur).parent / "fragments.json").read_text())
    assert "cmd7" in frags["cases"]
    states = []
    while not q.empty():
        states.append(q.get_nowait()["state"])
    assert states[:2] == ["queued", "thinking"] and states[-1] == "done"


async def test_next_ask_sends_the_current_fragments(tmp_path, boxes_dir):
    fb, store, runner, client = make(
        tmp_path, boxes_dir, golden("shake-head-on-7") + golden("fire-when-3-pressed")
    )
    await wait_done(runner, await runner.submit("ask", {"box": "testbox", "text": "shake on 7"}))
    await wait_done(runner, await runner.submit("ask", {"box": "testbox", "text": "fire on 3"}))
    assert "case cmd7" in client.calls[1]["messages"][0]["content"]


async def test_explain_ends_done_without_flashing(tmp_path, boxes_dir):
    fb, store, runner, client = make(tmp_path, boxes_dir, golden("make-it-fly"))
    job = await wait_done(
        runner, await runner.submit("ask", {"box": "testbox", "text": "make it fly"})
    )
    assert job.state == "done" and job.message_kid
    assert fb.uploads == 0 and store.current("testbox").id == "0000"


async def test_compile_error_retries_with_the_log(tmp_path, boxes_dir):
    fb, store, runner, client = make(tmp_path, boxes_dir, golden("compile-retry"))
    job = await wait_done(
        runner, await runner.submit("ask", {"box": "testbox", "text": "fire on 5"})
    )
    assert job.state == "done" and len(client.calls) == 2
    assert "expected ';'" in client.calls[1]["messages"][0]["content"]
    assert "cmd5" in fb.last_uploaded_source and "fire() break" not in fb.last_uploaded_source


async def test_three_bad_compiles_fail_in_kid_language(tmp_path, boxes_dir):
    bad = golden("compile-retry")[:1] * 3
    fb, store, runner, client = make(tmp_path, boxes_dir, bad)
    job = await wait_done(
        runner, await runner.submit("ask", {"box": "testbox", "text": "fire on 5"})
    )
    assert job.state == "failed" and len(client.calls) == 3
    assert "Traceback" not in job.message_kid and job.log_ref
    assert store.current("testbox").id == "0000"


async def test_api_failure_marks_the_helper_away(tmp_path, boxes_dir):
    fb, store, runner, client = make(tmp_path, boxes_dir, [{"error": "boom"}])
    job = await wait_done(runner, await runner.submit("ask", {"box": "testbox", "text": "x"}))
    assert job.state == "failed" and "away" in job.message_kid
    assert runner.genie_away() is True


async def test_refusal_sends_to_offline_path(tmp_path, boxes_dir):
    fb, store, runner, client = make(tmp_path, boxes_dir, [{"refusal": True}])
    job = await wait_done(runner, await runner.submit("ask", {"box": "testbox", "text": "x"}))
    assert job.state == "failed" and "Pick a trick" in job.message_kid
    assert runner.genie_away() is False  # a refusal is not an outage


async def test_no_genie_configured(tmp_path, boxes_dir):
    fb, store, runner, client = make(tmp_path, boxes_dir, [])
    runner.genie = lambda box_id: None
    job = await wait_done(runner, await runner.submit("ask", {"box": "testbox", "text": "x"}))
    assert job.state == "failed" and "away" in job.message_kid


def test_genie_refused_is_an_exception():
    assert issubclass(GenieRefused, Exception)


async def test_ask_sketch_dir_carries_the_stock_sketch_siblings(tmp_path, boxes_dir):
    box_dir = boxes_dir / "testbox" / "stock" / "stock"
    (box_dir / "config.h").write_text("int maxSpeed = 255;\n")
    fb, store, runner, client = make(tmp_path, boxes_dir, golden("fire-when-3-pressed"))
    job = await wait_done(
        runner, await runner.submit("ask", {"box": "testbox", "text": "fire on 3"})
    )
    assert job.state == "done"
    assert "config.h" in fb.last_sketch_files and "genie.ino" in fb.last_sketch_files
    cur = store.current("testbox")
    assert (store.path("testbox", cur) / "config.h").is_file()  # stored version keeps it too


async def test_guard_rejects_escaping_fragments_and_retries(tmp_path, boxes_dir):
    bad = {"kind": "sketch", "params": "#include <EEPROM.h>", "message_kid": "Done."}
    good = {"kind": "sketch", "cases": "case cmd7: fire(); break;", "message_kid": "Press 7."}
    fb, store, runner, client = make(tmp_path, boxes_dir, [bad, good])
    job = await wait_done(runner, await runner.submit("ask", {"box": "testbox", "text": "x"}))
    assert job.state == "done" and fb.uploads == 1
    assert len(client.calls) == 2
    assert "#include" in client.calls[1]["messages"][0]["content"]
    assert "EEPROM" not in fb.last_uploaded_source  # the skeleton has its own includes


async def test_guard_declines_an_explain_with_a_link(tmp_path, boxes_dir):
    bad = {"kind": "explain", "message_kid": "Watch https://example.com to learn servos."}
    fb, store, runner, client = make(tmp_path, boxes_dir, [bad])
    job = await wait_done(runner, await runner.submit("ask", {"box": "testbox", "text": "x"}))
    assert job.state == "failed" and "Pick a trick" in job.message_kid
    assert fb.uploads == 0 and runner.genie_away() is False
