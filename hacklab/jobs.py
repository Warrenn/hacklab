"""Job runner protocol and the fake runner used for dev and tests.

A job walks through stages and ends in `done` or `failed`. Every state change
is pushed to subscribers (the SSE route). P1 adds the real runner (arduino-cli
compile + upload) behind the same protocol.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from hacklab.flash import Flasher
    from hacklab.store import SketchStore

TERMINAL_STATES = {"done", "failed"}

STAGES = {
    "ask": ["thinking", "compiling", "uploading", "verifying"],
    "flash": ["compiling", "uploading", "verifying"],
    "undo": ["uploading", "verifying"],
    "reset": ["uploading", "verifying"],
}

# Kid-facing stage text. Generated server-side so the PWA stays dumb.
MESSAGES = {
    "queued": "Getting ready.",
    "thinking": "The AI helper is thinking about your idea.",
    "compiling": "Turning the code into robot language.",
    "uploading": "Sending it to the box. Do not unplug it.",
    "verifying": "Checking the box woke up again.",
    "done": "Done! Watch the box.",
    "failed": "That one did not work. Try again, or press Undo.",
}


@dataclass
class Job:
    id: str
    kind: str
    payload: dict[str, Any]
    state: str = "queued"
    message_kid: str = MESSAGES["queued"]
    log_ref: str | None = None
    prompts: list[dict[str, str]] = field(default_factory=list)
    sketch_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.id,
            "kind": self.kind,
            "state": self.state,
            "message_kid": self.message_kid,
            "log_ref": self.log_ref,
            "prompts": self.prompts,
            "sketch_ref": self.sketch_ref,
        }


OnDone = Callable[[Job], None]


class JobRunner(Protocol):
    async def submit(
        self, kind: str, payload: dict[str, Any], on_done: OnDone | None = None
    ) -> str: ...
    def get(self, job_id: str) -> Job | None: ...
    def subscribe(self) -> asyncio.Queue: ...
    def unsubscribe(self, queue: asyncio.Queue) -> None: ...


class FakeJobRunner:
    """Walks the stages on a timer. payload["fail"] fails it at compile time;
    payload["prompts"] is attached on success."""

    def __init__(self, delay: float = 1.0):
        self.delay = delay
        self.jobs: dict[str, Job] = {}
        self._subscribers: set[asyncio.Queue] = set()
        self._tasks: set[asyncio.Task] = set()

    async def submit(
        self, kind: str, payload: dict[str, Any], on_done: OnDone | None = None
    ) -> str:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, payload=payload)
        self.jobs[job.id] = job
        self._publish(job)
        task = asyncio.create_task(self._run(job, on_done))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job.id

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(q)
        return q

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def _set(self, job: Job, state: str) -> None:
        job.state = state
        job.message_kid = MESSAGES[state]
        self._publish(job)

    def _publish(self, job: Job) -> None:
        for q in self._subscribers:
            q.put_nowait(job.to_dict())

    async def _run(self, job: Job, on_done: OnDone | None) -> None:
        for stage in STAGES[job.kind]:
            self._set(job, stage)
            await asyncio.sleep(self.delay)
            if stage == "compiling" and job.payload.get("fail"):
                job.log_ref = f"{job.id}.log"
                self._set(job, "failed")
                return
        job.sketch_ref = f"{job.id}.ino"
        job.prompts = job.payload.get("prompts", [])
        if on_done:
            on_done(job)
        self._set(job, "done")


class RealJobRunner:
    """Flasher + SketchStore behind the JobRunner protocol. One job at a time
    (ponytail: global lock -- one box, one USB cable). Blocking work runs in a
    thread so SSE keeps streaming."""

    def __init__(self, flasher: Flasher, store: SketchStore, work_dir: Path | str):
        self.flasher, self.store, self.work_dir = flasher, store, Path(work_dir)
        self.jobs: dict[str, Job] = {}
        self._subscribers: set[asyncio.Queue] = set()
        self._tasks: set[asyncio.Task] = set()
        self._lock = asyncio.Lock()

    async def submit(
        self, kind: str, payload: dict[str, Any], on_done: OnDone | None = None
    ) -> str:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, payload=payload)
        self.jobs[job.id] = job
        self._publish(job)
        task = asyncio.create_task(self._run(job, on_done))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job.id

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(q)
        return q

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def _set(self, job: Job, state: str, message: str | None = None) -> None:
        job.state = state
        job.message_kid = message or MESSAGES[state]
        self._publish(job)

    def _publish(self, job: Job) -> None:
        for q in self._subscribers:
            q.put_nowait(job.to_dict())

    def _sketch_dir(self, job: Job) -> Path | None:
        """Where the sketch to flash lives: a stored version (undo/reset), a
        given directory, or `source` written as <box>.ino in a temp dir."""
        box = job.payload["box"]
        if job.kind == "undo":
            v = self.store.previous(box)
        elif job.kind == "reset":
            v = self.store.baseline(box)
        else:
            if job.payload.get("sketch_dir"):
                return Path(job.payload["sketch_dir"])
            # arduino-cli needs <dir>/<dir>.ino; the temp parent carries the random name.
            d = Path(tempfile.mkdtemp(prefix=f"{box}-", dir=self._mk(self.work_dir))) / "sketch"
            d.mkdir()
            (d / "sketch.ino").write_text(job.payload.get("source", ""))
            return d
        if v is None:
            return None
        job.sketch_ref = v.id
        return self.store.path(box, v)

    async def _run(self, job: Job, on_done: OnDone | None) -> None:
        box = job.payload["box"]
        async with self._lock:
            try:
                await self._run_locked(job, box, on_done)
            except Exception as exc:  # noqa: BLE001 - a bug must surface as a failed job, never a hang
                job.log_ref = self._write_log(
                    box, job, f"internal error: {type(exc).__name__}: {exc}"
                )
                self._set(job, "failed")

    async def _run_locked(self, job: Job, box: str, on_done: OnDone | None) -> None:
        if True:
            sketch_dir = self._sketch_dir(job)
            if sketch_dir is None:
                self._set(job, "failed")
                return
            loop = asyncio.get_running_loop()
            progress = lambda stage: loop.call_soon_threadsafe(self._set, job, stage)  # noqa: E731
            res = await asyncio.to_thread(self.flasher.flash, box, sketch_dir, progress)
            job.log_ref = self._write_log(box, job, res.log)
            if not res.ok:
                self._set(job, "failed", res.message_kid or MESSAGES["failed"])
                return
            if job.kind == "undo":
                self.store.pop(box)
            elif job.kind == "reset":
                self.store.truncate_to_baseline(box)
            else:
                v = self.store.save(
                    box, sketch_dir, kind=job.kind, note=job.payload.get("text", "")
                )
                job.sketch_ref = v.id
                if not job.payload.get("sketch_dir"):
                    shutil.rmtree(sketch_dir.parent, ignore_errors=True)
            job.prompts = job.payload.get("prompts", [])
            if on_done:
                on_done(job)
            self._set(job, "done")

    def _write_log(self, box: str, job: Job, text: str) -> str:
        logs = self._mk(self.store.root / box / "logs")
        (logs / f"{job.id}.log").write_text(text)
        return f"{job.id}.log"

    @staticmethod
    def _mk(p: Path) -> Path:
        p.mkdir(parents=True, exist_ok=True)
        return p
