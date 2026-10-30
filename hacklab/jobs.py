"""Job runner protocol and the fake runner used for dev and tests.

A job walks through stages and ends in `done` or `failed`. Every state change
is pushed to subscribers (the SSE route). P1 adds the real runner (arduino-cli
compile + upload) behind the same protocol.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from hacklab.flash import Flasher
    from hacklab.genie import Genie
    from hacklab.spend import SpendLedger
    from hacklab.store import SketchStore

KID_AWAY = "The AI helper is away right now. Pick a trick instead."
KID_DECLINED = "The AI helper can't help with that one. Pick a trick instead."
KID_GAVE_UP = (
    "The AI helper tried three times and the code would not build. "
    "Try saying it another way, or pick a trick."
)
GenieFactory = Callable[[str], "Genie | None"]

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

    def broadcast(self, event: dict[str, Any]) -> None:
        for q in self._subscribers:
            q.put_nowait(event)

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

    def __init__(
        self,
        flasher: Flasher,
        store: SketchStore,
        work_dir: Path | str,
        genie: GenieFactory | None = None,
        ledger: SpendLedger | None = None,
        spec_for: Callable[[str], Any] | None = None,
    ):
        self.flasher, self.store, self.work_dir = flasher, store, Path(work_dir)
        self.genie, self.ledger, self.spec_for = genie, ledger, spec_for
        self._away_until = 0.0
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

    def broadcast(self, event: dict[str, Any]) -> None:
        for q in self._subscribers:
            q.put_nowait(event)

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

    def _spec(self, box: str):
        return self.spec_for(box) if self.spec_for else None

    # -- genie availability ------------------------------------------------
    def genie_away(self) -> bool:
        return time.time() < self._away_until

    def mark_away(self, minutes: float = 10) -> None:
        self._away_until = time.time() + minutes * 60

    async def _run_locked(self, job: Job, box: str, on_done: OnDone | None) -> None:
        if job.kind == "ask":
            await self._run_ask(job, box, on_done)
            return
        if True:
            sketch_dir = self._sketch_dir(job)
            if sketch_dir is None:
                self._set(job, "failed")
                return
            loop = asyncio.get_running_loop()
            progress = lambda stage: loop.call_soon_threadsafe(self._set, job, stage)  # noqa: E731
            res = await asyncio.to_thread(
                self.flasher.flash, box, sketch_dir, progress, self._spec(box)
            )
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

    # -- the AI helper --------------------------------------------------------
    def _current_fragments(self, box: str):
        from hacklab.skeleton import Fragments

        cur = self.store.current(box)
        f = self.store.version_dir(box, cur) / "fragments.json" if cur else None
        return Fragments.from_dict(json.loads(f.read_text())) if f and f.is_file() else Fragments()

    def _log_ask(self, box: str, entry: dict[str, Any]) -> None:
        logs = self._mk(self.store.root / box / "logs")
        with (logs / "asks.jsonl").open("a") as f:
            f.write(json.dumps({"ts": int(time.time()), **entry}) + "\n")

    async def _run_ask(self, job: Job, box: str, on_done: OnDone | None) -> None:
        from hacklab.genie import GenieRefused, prompts_for
        from hacklab.skeleton import assemble

        text = job.payload.get("text", "")
        t0 = time.time()
        src = (
            "tailscale" if job.payload.get("origin") == "remote" else "local"
        )  # owner's log wording
        self._set(job, "thinking")
        genie = self.genie(box) if self.genie else None
        if genie is None:
            self._set(job, "failed", KID_AWAY)
            return
        current = self._current_fragments(box)
        error: str | None = None
        log: list[str] = []
        loop = asyncio.get_running_loop()
        progress = lambda stage: loop.call_soon_threadsafe(self._set, job, stage)  # noqa: E731
        for attempt in range(1, 4):
            try:
                result, usage = await asyncio.to_thread(genie.ask, text, current, error)
            except GenieRefused as exc:
                log.append(f"refused: {exc}")
                job.log_ref = self._write_log(box, job, "\n".join(log))
                self._log_ask(
                    box, {"request": text, "box": box, "kind": "refusal", "attempts": attempt}
                )
                self._set(job, "failed", KID_DECLINED)
                return
            except Exception as exc:  # noqa: BLE001 - network/API trouble => helper is away
                log.append(f"api error: {type(exc).__name__}: {exc}")
                job.log_ref = self._write_log(box, job, "\n".join(log))
                self._log_ask(
                    box, {"request": text, "box": box, "kind": "error", "error": str(exc)[:300]}
                )
                self.mark_away()
                self._set(job, "failed", KID_AWAY)
                return
            if self.ledger:
                self.ledger.record(genie.model, usage)
            entry = {
                "request": text,
                "box": box,
                "source": src,
                "kind": result.kind,
                "attempts": attempt,
                "usage": {
                    "in": getattr(usage, "input_tokens", 0),
                    "out": getattr(usage, "output_tokens", 0),
                    "cache_read": getattr(usage, "cache_read_input_tokens", 0),
                },
            }
            if result.kind != "sketch":
                job.prompts = []
                self._log_ask(box, {**entry, "duration_s": round(time.time() - t0, 1)})
                self._set(job, "done", result.message_kid)
                return
            frags = result.fragments()
            parent = Path(tempfile.mkdtemp(prefix=f"{box}-ask-", dir=self._mk(self.work_dir)))
            sketch_dir = parent / "genie"
            sketch_dir.mkdir()
            # multi-file boxes: #include siblings (config.h ...) come from the baseline copy
            base = self.store.baseline(box)
            stock = self.store.path(box, base) if base else genie.box.stock_dir(self.store.root)
            for f in stock.iterdir() if stock.is_dir() else []:
                if f.is_file() and f.suffix != ".ino":
                    shutil.copy2(f, sketch_dir / f.name)
            (sketch_dir / "genie.ino").write_text(assemble(genie.skeleton, frags))
            res = await asyncio.to_thread(
                self.flasher.flash, box, sketch_dir, progress, self._spec(box)
            )
            log.append(f"[attempt {attempt}] {res.log}")
            if res.ok:
                v = self.store.save(box, sketch_dir, kind="ask", note=text)
                (self.store.version_dir(box, v) / "fragments.json").write_text(
                    json.dumps(frags.to_dict())
                )
                shutil.rmtree(parent, ignore_errors=True)
                job.sketch_ref = v.id
                job.prompts = prompts_for(result, genie.box)
                job.log_ref = self._write_log(box, job, "\n".join(log))
                self._log_ask(
                    box,
                    {
                        **entry,
                        "version": v.id,
                        "changed": result.changed,
                        "duration_s": round(time.time() - t0, 1),
                    },
                )
                if on_done:
                    on_done(job)
                self._set(job, "done", result.message_kid)
                return
            shutil.rmtree(parent, ignore_errors=True)
            if res.failed_stage != "compiling":
                job.log_ref = self._write_log(box, job, "\n".join(log))
                self._log_ask(box, {**entry, "failed_stage": res.failed_stage})
                self._set(job, "failed", res.message_kid)
                return
            error = res.log
        job.log_ref = self._write_log(box, job, "\n".join(log))
        self._log_ask(
            box, {"request": text, "box": box, "source": src, "kind": "gave-up", "attempts": 3}
        )
        self._set(job, "failed", KID_GAVE_UP)
