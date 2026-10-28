"""Job runner protocol and the fake runner used for dev and tests.

A job walks through stages and ends in `done` or `failed`. Every state change
is pushed to subscribers (the SSE route). P1 adds the real runner (arduino-cli
compile + upload) behind the same protocol.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

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
