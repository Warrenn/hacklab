"""RealJobRunner: same protocol/stages as FakeJobRunner, backed by Flasher + SketchStore."""

import asyncio
from pathlib import Path

import pytest

from hacklab.board import FakeBoard
from hacklab.flash import Flasher
from hacklab.jobs import MESSAGES, RealJobRunner
from hacklab.store import SketchStore

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def env(tmp_path: Path):
    fb = FakeBoard()
    store = SketchStore(tmp_path / "data")
    stock = tmp_path / "stock"
    stock.mkdir()
    (stock / "stock.ino").write_text("// stock")
    store.ensure_baseline("b", stock)
    flasher = Flasher(fb, data_dir=tmp_path / "data", reenumerate_timeout=0.2, sleep=lambda s: None)
    return fb, store, RealJobRunner(flasher, store, work_dir=tmp_path / "work")


async def wait_done(runner, job_id, timeout=5.0):
    async def _w():
        while runner.get(job_id).state not in {"done", "failed"}:
            await asyncio.sleep(0.01)

    await asyncio.wait_for(_w(), timeout)
    return runner.get(job_id)


async def test_flash_source_saves_version_and_walks_stages(env):
    fb, store, runner = env
    q = runner.subscribe()
    job_id = await runner.submit("flash", {"box": "b", "source": "void loop(){}"})
    job = await wait_done(runner, job_id)
    assert job.state == "done" and job.message_kid == MESSAGES["done"]
    assert job.sketch_ref == "0001" and store.current("b").id == "0001"
    assert store.main_source("b", store.current("b")) == "void loop(){}"
    seen = []
    while not q.empty():
        seen.append(q.get_nowait()["state"])
    assert seen == ["queued", "compiling", "uploading", "verifying", "done"]


async def test_compile_failure_sets_failed_and_log_ref(env, tmp_path: Path):
    fb, store, runner = env
    fb.compile_error = "error: nope"
    job = await wait_done(runner, await runner.submit("flash", {"box": "b", "source": "x"}))
    assert job.state == "failed"
    assert job.log_ref and (tmp_path / "data" / "b" / "logs" / job.log_ref).read_text().count(
        "nope"
    )
    assert store.current("b").id == "0000"  # nothing recorded


async def test_no_board_uses_kid_message(env):
    fb, store, runner = env
    fb.unplugged = True
    job = await wait_done(runner, await runner.submit("flash", {"box": "b", "source": "x"}))
    assert job.state == "failed" and "plugged in" in job.message_kid


async def test_undo_flashes_previous_then_pops(env):
    fb, store, runner = env
    await wait_done(runner, await runner.submit("flash", {"box": "b", "source": "one"}))
    await wait_done(runner, await runner.submit("flash", {"box": "b", "source": "two"}))
    job = await wait_done(runner, await runner.submit("undo", {"box": "b"}))
    assert job.state == "done" and job.sketch_ref == "0001"
    assert store.current("b").id == "0001"
    assert fb.last_uploaded_source == "one"


async def test_undo_at_baseline_fails_cleanly(env):
    fb, store, runner = env
    job = await wait_done(runner, await runner.submit("undo", {"box": "b"}))
    assert job.state == "failed" and fb.uploads == 0


async def test_reset_flashes_baseline_and_truncates(env):
    fb, store, runner = env
    await wait_done(runner, await runner.submit("flash", {"box": "b", "source": "one"}))
    job = await wait_done(runner, await runner.submit("reset", {"box": "b"}))
    assert job.state == "done" and job.sketch_ref == "0000"
    assert [v.id for v in store.versions("b")] == ["0000"]
    assert fb.last_uploaded_source == "// stock"


async def test_failed_undo_keeps_versions(env):
    fb, store, runner = env
    await wait_done(runner, await runner.submit("flash", {"box": "b", "source": "one"}))
    fb.upload_fails_for = {"atmega328", "atmega328old"}
    job = await wait_done(runner, await runner.submit("undo", {"box": "b"}))
    assert job.state == "failed" and store.current("b").id == "0001"


async def test_jobs_run_one_at_a_time(env):
    fb, store, runner = env
    ids = [await runner.submit("flash", {"box": "b", "source": str(i)}) for i in range(3)]
    for i in ids:
        await wait_done(runner, i)
    assert fb.max_concurrent == 1
    assert [v.id for v in store.versions("b")] == ["0000", "0001", "0002", "0003"]


async def test_source_payload_becomes_a_validly_named_sketch_dir(env):
    fb, store, runner = env
    job = await wait_done(
        runner, await runner.submit("flash", {"box": "omnibot-forklift", "source": "void loop(){}"})
    )
    assert job.state == "failed"  # no baseline for this box yet -> clean failure, no crash
    store.ensure_baseline("omnibot-forklift", store.path("b", store.baseline("b")))
    job = await wait_done(
        runner, await runner.submit("flash", {"box": "omnibot-forklift", "source": "void loop(){}"})
    )
    assert job.state == "done"
    d = store.path("omnibot-forklift", store.current("omnibot-forklift"))
    assert (d / f"{d.name}.ino").read_text() == "void loop(){}"
