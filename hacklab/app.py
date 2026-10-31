"""FastAPI app implementing the PWA <-> backend contract (STRATEGY.md)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import shutil
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from hacklab.board import ArduinoCli, Board, FakeBoard, board_spec
from hacklab.config import Config, load_config
from hacklab.flash import Flasher
from hacklab.genie import Genie
from hacklab.jobs import FakeJobRunner, JobRunner, RealJobRunner
from hacklab.profiles import Behaviour, load_boxes
from hacklab.remote import MSG_NO_SWITCH, MSG_REMOTE_VIEW, Helping, source_of
from hacklab.skeleton import load_skeleton
from hacklab.spend import SpendLedger
from hacklab.store import SketchStore
from hacklab.templates import TemplateError, render

log = logging.getLogger("hacklab.app")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
PLACEHOLDER = (
    "<!doctype html><title>Hack Lab</title>"
    "<p>Hack Lab is starting up. The app screen arrives with P3.</p>"
)

STOCK = "stock"


class BoxSelect(BaseModel):
    id: str


class FlashBehaviour(BaseModel):
    id: str
    tweakables: dict[str, Any] | None = Field(default=None, max_length=32)


class FlashTemplate(BaseModel):
    template_id: str
    values: dict[str, Any] = Field(max_length=32)


class FlashSketch(BaseModel):
    source: str = Field(max_length=256 * 1024)  # Level 3: a whole sketch, never a dump


class Ask(BaseModel):
    text: str = Field(min_length=1, max_length=500)


# P7b: the appliance answers only for its own names (the kid's browser must not be usable as a
# bridge to it from a malicious page: CSRF, DNS rebinding). IP literals and Tailscale MagicDNS
# names are fine; "testserver" is Starlette's TestClient default.
OWN_HOST = re.compile(
    r"^(hacklab(\.local)?|localhost|testserver|\d{1,3}(\.\d{1,3}){3}|[0-9a-f:]+|[a-z0-9-]+\.[a-z0-9-]+\.ts\.net)$",
    re.I,
)
MSG_BAD_HOST = "This address is not the Hack Lab."
MSG_CROSS_SITE = "Changes must come from the Hack Lab page itself."


def host_of(value: str) -> str:
    """'hacklab.local:80' / '[fd7a::1]:80' / 'http://x' -> bare host, lower-case."""
    v = value if "//" in value else "//" + value
    return (urlsplit(v).hostname or "").lower()


class HelpingBody(BaseModel):
    on: bool


def format_sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


def make_runner(
    cfg: Config, board: Board | None = None
) -> tuple[JobRunner, Flasher | None, SketchStore | None]:
    """FAKE_BOARD=1 -> FakeJobRunner (PWA mock, no compile, no API). Otherwise the
    real runner on the given board, FakeBoard when HACKLAB_BOARD=fake, or
    arduino-cli from the toolchain prefix."""
    if cfg.fake_board and board is None:
        return FakeJobRunner(), None, None
    if board is None:
        board = (
            FakeBoard() if cfg.board == "fake" else ArduinoCli(cfg.arduino_cli, cfg.arduino_config)
        )
    store = SketchStore(cfg.data_dir)
    flasher = Flasher(board, cfg.data_dir)
    runner = RealJobRunner(flasher, store, cfg.data_dir / "work", ledger=SpendLedger(cfg.data_dir))
    return runner, flasher, store


def make_genie_client(cfg: Config):
    if not cfg.api_key:
        return None
    if os.environ.get("HACKLAB_GENIE") == "golden":  # full-stack tests: replay tests/golden, no API
        from hacklab.genie import GoldenGenieClient

        return GoldenGenieClient()
    import anthropic  # imported here so the mock backend never needs the SDK

    return anthropic.Anthropic(api_key=cfg.api_key, max_retries=1, timeout=60.0)


def _mk(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def create_app(
    config: Config | None = None,
    runner: JobRunner | None = None,
    board: Board | None = None,
    genie_client: Any = None,
) -> FastAPI:
    cfg = config or load_config()
    flasher = store = None
    if runner is None:
        runner, flasher, store = make_runner(cfg, board)
    boxes = load_boxes(cfg.boxes_dir)
    client = (genie_client or make_genie_client(cfg)) if store else None

    def genie_for(box_id: str) -> Genie | None:
        """The AI helper for a box, or None when it is away: no key, over the
        monthly cap, backing off after an API error, or no skeleton for the box."""
        if cfg.api_key is None or client is None or box_id not in boxes:
            return None
        if getattr(runner, "genie_away", lambda: False)():
            return None
        skeleton = load_skeleton(boxes[box_id], cfg.data_dir)
        if skeleton is None:
            return None
        return Genie(client, cfg.model, boxes[box_id], skeleton)

    def spec_for(box_id: str):
        return board_spec(boxes[box_id].fqbn) if box_id in boxes else None

    if isinstance(runner, RealJobRunner):
        runner.genie = genie_for
        runner.spec_for = spec_for
    helping = Helping(cfg.data_dir / "helping.jsonl")

    def source(request: Request) -> str:
        return source_of(request, allow_header=cfg.fake_board)

    def writable(request: Request) -> str:
        """Remote viewers may only change things while helping is on."""
        src = source(request)
        if src == "remote" and not helping.is_on():
            raise HTTPException(403, MSG_REMOTE_VIEW)
        return src

    async def watch_board() -> None:
        """Push {"type": "status"} the moment a serial device appears or vanishes, so
        every open page shows plug/unplug within ~1 s instead of the 20 s poll."""
        last: frozenset[str] | None = None
        while True:
            try:
                nodes = await asyncio.to_thread(flasher.board.device_nodes)
                if last is not None and nodes != last:
                    box = state["box"]
                    await asyncio.to_thread(flasher.detect, True, spec_for(box) if box else None)
                    runner.broadcast({"type": "status"})
                last = nodes
            except Exception:  # keep watching; a bad listing must not kill the watcher
                log.exception("board watch")
            await asyncio.sleep(cfg.watch_interval)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        task = asyncio.create_task(watch_board()) if flasher else None
        yield
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="Hack Lab", lifespan=lifespan)
    app.state.runner = runner

    @app.middleware("http")
    async def host_guard(request: Request, call_next):
        host = host_of(request.headers.get("host", ""))
        if not (OWN_HOST.match(host) or host in cfg.allowed_hosts):
            return JSONResponse({"detail": MSG_BAD_HOST}, status_code=400)
        origin = request.headers.get("origin")
        if request.method == "POST" and origin and host_of(origin) != host:
            return JSONResponse({"detail": MSG_CROSS_SITE}, status_code=403)
        return await call_next(request)

    state: dict[str, Any] = {"box": None, "versions": {}}  # mock mode only: box_id -> [version]

    def box_or_409() -> str:
        if not state["box"]:
            raise HTTPException(409, "Pick a box first.")
        return state["box"]

    def versions() -> list[str]:
        box = box_or_409()
        if store:
            return [v.id for v in store.versions(box)]
        return state["versions"].setdefault(box, [STOCK])

    def ensure_baseline(box_id: str) -> None:
        if store and store.baseline(box_id) is None:
            stock = boxes[box_id].stock_dir(cfg.data_dir)
            if not stock.is_dir():
                raise HTTPException(409, "The stock code for this box is not on the device yet.")
            store.ensure_baseline(box_id, stock)

    def rendered_sketch_dir(item: Behaviour, values: dict[str, Any] | None) -> Path:
        """Copy the behaviour/template sketch dir and rewrite its main file with the
        tweaked values; the copy keeps the <id>/<id>.ino name arduino-cli needs."""
        try:
            source = render(item.source(), values or {})
        except TemplateError as exc:
            raise HTTPException(422, str(exc)) from exc
        parent = Path(tempfile.mkdtemp(prefix="render-", dir=_mk(cfg.data_dir / "work")))
        d = parent / item.id
        shutil.copytree(item.sketch_dir, d)
        (d / f"{item.id}.ino").write_text(source)
        return d

    async def start(kind: str, payload: dict[str, Any], src: str = "local") -> dict[str, str]:
        box = box_or_409()
        payload = {**payload, "box": box, "origin": src}  # not "source": that is a sketch field
        vs = None if store else versions()

        def on_done(job):
            # Mock mode keeps versions in memory; never record for another box.
            if vs is None or state["box"] != box:
                return
            if kind == "undo":
                vs.pop()
            elif kind == "reset":
                del vs[1:]
            else:
                vs.append(job.sketch_ref)

        return {"job_id": await runner.submit(kind, payload, on_done)}

    @app.get("/api/status")
    def status(request: Request):
        box = state["box"]
        vs = versions() if box else []
        return {
            "box": box,
            "online": True,
            # The spend budget lives only in the Claude Console: when it is reached the API
            # refuses and the runner marks the helper away; there is no cap here.
            "ai_available": (
                cfg.api_key is not None and (store is None or genie_for(box) is not None)
                if box
                else cfg.api_key is not None
            ),
            "board_connected": (
                flasher.detect(spec=spec_for(box) if box else None) is not None
                if flasher
                else cfg.fake_board
            ),
            "current_version": vs[-1] if vs else None,
            "versions_count": len(vs),
            "source": source(request),
            "helping": helping.is_on(),
        }

    @app.post("/api/helping")
    def set_helping(body: HelpingBody, request: Request):
        if source(request) != "remote":
            raise HTTPException(403, MSG_NO_SWITCH)
        on = helping.set(body.on, request.client.host if request.client else None)
        runner.broadcast({"type": "status", "helping": on})
        return {"helping": on}

    @app.get("/api/boxes")
    def list_boxes():
        return [b.to_api() for b in boxes.values()]

    @app.post("/api/box")
    def select_box(body: BoxSelect, request: Request):
        writable(request)
        if body.id not in boxes:
            raise HTTPException(404, "No such box.")
        ensure_baseline(body.id)  # may 409: the box stays unselected
        state["box"] = body.id
        state["versions"].setdefault(body.id, [STOCK])
        return {"box": body.id}

    @app.get("/api/behaviours")
    def behaviours():
        return [b.to_api() for b in boxes[box_or_409()].behaviours.values()]

    @app.post("/api/flash/behaviour")
    async def flash_behaviour(body: FlashBehaviour, request: Request):
        src = writable(request)
        item = boxes[box_or_409()].behaviours.get(body.id)
        if item is None:
            raise HTTPException(404, "No such behaviour.")
        d = rendered_sketch_dir(item, body.tweakables)
        return await start("flash", {"id": body.id, "sketch_dir": str(d), "text": item.title}, src)

    @app.post("/api/flash/template")
    async def flash_template(body: FlashTemplate, request: Request):
        src = writable(request)
        item = boxes[box_or_409()].templates.get(body.template_id)
        if item is None:
            raise HTTPException(404, "No such template.")
        d = rendered_sketch_dir(item, body.values)
        payload = {"template_id": body.template_id, "sketch_dir": str(d), "text": item.title}
        return await start("flash", payload, src)

    @app.post("/api/flash/sketch")
    async def flash_sketch(body: FlashSketch, request: Request):
        return await start("flash", body.model_dump(), writable(request))

    @app.post("/api/ask")
    async def ask(body: Ask, request: Request):
        src = writable(request)
        text = body.text.strip()
        box = box_or_409()
        if store and genie_for(box) is None:
            raise HTTPException(409, "The AI helper is away right now. Pick a trick instead.")
        payload = {
            "text": text,
            "fail": text.lower().startswith("fail"),  # mock-only: exercises the failure path
            "prompts": [],  # mock-only; the real runner fills prompts from the genie
        }
        return await start("ask", payload, src)

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        j = runner.get(job_id)
        if j is None:
            raise HTTPException(404, "No such job.")
        return j.to_dict()

    @app.post("/api/undo")
    async def undo(request: Request):
        src = writable(request)
        if len(versions()) < 2:
            raise HTTPException(409, "Nothing to undo.")
        return await start("undo", {}, src)

    @app.post("/api/reset")
    async def reset(request: Request):
        return await start("reset", {}, writable(request))

    @app.get("/api/sketch/current")
    def sketch_current():
        box = box_or_409()
        if store:
            cur = store.current(box)
            return {"source": store.main_source(box, cur), "version": cur.id, "box": box}
        b = boxes[box]
        stock = b.stock_dir(cfg.data_dir) / f"{b.stock_main}.ino"
        source = stock.read_text() if stock.is_file() else ""
        return {"source": source, "version": versions()[-1], "box": box}

    @app.get("/api/concepts/{concept_id}")
    def concept(concept_id: str):
        c = boxes[box_or_409()].concepts.get(concept_id)
        if c is None:
            raise HTTPException(404, "No such concept.")
        return c.to_api()

    @app.get("/api/events")
    async def events(request: Request):
        async def stream() -> AsyncIterator[str]:
            q = runner.subscribe()
            try:
                while not await request.is_disconnected():
                    try:
                        yield format_sse(await asyncio.wait_for(q.get(), timeout=15))
                    except TimeoutError:
                        yield ": ping\n\n"
            finally:
                runner.unsubscribe(q)

        return StreamingResponse(stream(), media_type="text/event-stream")

    # The PWA (P3): static/index.html at /, assets under /static.
    @app.get("/", response_class=HTMLResponse)
    def index():
        page = STATIC_DIR / "index.html"
        return page.read_text() if page.is_file() else PLACEHOLDER

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app


app = create_app()
