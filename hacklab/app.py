"""FastAPI app implementing the PWA <-> backend contract (STRATEGY.md)."""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from hacklab.board import ArduinoCli, Board
from hacklab.config import Config, load_config
from hacklab.flash import Flasher
from hacklab.jobs import FakeJobRunner, JobRunner, RealJobRunner
from hacklab.profiles import Behaviour, load_boxes
from hacklab.store import SketchStore
from hacklab.templates import TemplateError, render

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
    tweakables: dict[str, Any] | None = None


class FlashTemplate(BaseModel):
    template_id: str
    values: dict[str, Any]


class FlashSketch(BaseModel):
    source: str


class Ask(BaseModel):
    text: str = Field(min_length=1)


def format_sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


def make_runner(
    cfg: Config, board: Board | None = None
) -> tuple[JobRunner, Flasher | None, SketchStore | None]:
    """FAKE_BOARD=1 -> FakeJobRunner (mock backend). Otherwise the real runner
    on the given board, or arduino-cli from the config/toolchain prefix."""
    if cfg.fake_board and board is None:
        return FakeJobRunner(), None, None
    board = board or ArduinoCli(cfg.arduino_cli, cfg.arduino_config)
    store = SketchStore(cfg.data_dir)
    flasher = Flasher(board, cfg.data_dir)
    return RealJobRunner(flasher, store, cfg.data_dir / "work"), flasher, store


def _mk(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def create_app(
    config: Config | None = None, runner: JobRunner | None = None, board: Board | None = None
) -> FastAPI:
    cfg = config or load_config()
    flasher = store = None
    if runner is None:
        runner, flasher, store = make_runner(cfg, board)
    boxes = load_boxes(cfg.boxes_dir)
    app = FastAPI(title="Hack Lab")
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

    async def start(kind: str, payload: dict[str, Any]) -> dict[str, str]:
        box = box_or_409()
        payload = {**payload, "box": box}
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
    def status():
        box = state["box"]
        vs = versions() if box else []
        return {
            "box": box,
            "online": True,
            "ai_available": cfg.api_key is not None,
            "board_connected": flasher.detect() is not None if flasher else cfg.fake_board,
            "current_version": vs[-1] if vs else None,
            "versions_count": len(vs),
        }

    @app.get("/api/boxes")
    def list_boxes():
        return [b.to_api() for b in boxes.values()]

    @app.post("/api/box")
    def select_box(body: BoxSelect):
        if body.id not in boxes:
            raise HTTPException(404, "No such box.")
        state["box"] = body.id
        ensure_baseline(body.id)
        state["versions"].setdefault(body.id, [STOCK])
        return {"box": body.id}

    @app.get("/api/behaviours")
    def behaviours():
        return [b.to_api() for b in boxes[box_or_409()].behaviours.values()]

    @app.post("/api/flash/behaviour")
    async def flash_behaviour(body: FlashBehaviour):
        item = boxes[box_or_409()].behaviours.get(body.id)
        if item is None:
            raise HTTPException(404, "No such behaviour.")
        d = rendered_sketch_dir(item, body.tweakables)
        return await start("flash", {"id": body.id, "sketch_dir": str(d), "text": item.title})

    @app.post("/api/flash/template")
    async def flash_template(body: FlashTemplate):
        item = boxes[box_or_409()].templates.get(body.template_id)
        if item is None:
            raise HTTPException(404, "No such template.")
        d = rendered_sketch_dir(item, body.values)
        payload = {"template_id": body.template_id, "sketch_dir": str(d), "text": item.title}
        return await start("flash", payload)

    @app.post("/api/flash/sketch")
    async def flash_sketch(body: FlashSketch):
        return await start("flash", body.model_dump())

    @app.post("/api/ask")
    async def ask(body: Ask):
        text = body.text.strip()
        payload = {
            "text": text,
            "fail": text.lower().startswith("fail"),  # mock-only: exercises the failure path
            "prompts": [],  # P4: curiosity prompts from the genie
        }
        return await start("ask", payload)

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        j = runner.get(job_id)
        if j is None:
            raise HTTPException(404, "No such job.")
        return j.to_dict()

    @app.post("/api/undo")
    async def undo():
        if len(versions()) < 2:
            raise HTTPException(409, "Nothing to undo.")
        return await start("undo", {})

    @app.post("/api/reset")
    async def reset():
        return await start("reset", {})

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
