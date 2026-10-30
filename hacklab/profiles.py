"""Box profiles: everything box-specific, loaded from boxes/<id>/ (STRATEGY.md).

TOML instead of YAML (stdlib `tomllib`, same format as config.toml). Loading
validates eagerly and raises ProfileError naming the file and the problem, so a
broken profile fails at startup / in check-box.sh, never in front of the kid.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hacklab.templates import TemplateError, Tweakable, find_tweakables

REPO = Path(__file__).resolve().parent.parent
DEFAULT_BOXES = REPO / "boxes"
DEFAULT_WHITELIST = REPO / "provisioning" / "libraries.txt"
MAX_PIN = 21  # Nano: D0-D13, A0-A7 (14-21)


class ProfileError(ValueError):
    pass


@dataclass
class Concept:
    id: str
    title: str
    explanation: str
    tags: list[str] = field(default_factory=list)

    def to_api(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "explanation": self.explanation}


@dataclass
class Behaviour:
    id: str
    kind: str  # "behaviour" | "template"
    title: str
    description: str
    sketch_dir: Path
    tweakables: list[Tweakable]
    tested: str = ""
    trigger: str = ""
    action: str = ""
    concepts: list[str] = field(default_factory=list)

    @property
    def main_file(self) -> Path:
        return self.sketch_dir / f"{self.id}.ino"

    def source(self) -> str:
        return self.main_file.read_text()

    def to_api(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "tweakables": [t.to_api() for t in self.tweakables],
        }


@dataclass
class Box:
    id: str
    name: str
    picture: str
    root: Path
    fqbn: str
    core: str
    libraries: list[str]
    stock_location: str
    stock_main: str
    pins: dict[str, int]
    limits: dict[str, Any]
    hardware_md: str
    behaviours: dict[str, Behaviour]
    templates: dict[str, Behaviour]
    concepts: dict[str, Concept]

    def stock_dir(self, data_dir: Path) -> Path:
        if self.stock_location == "repo":
            return self.root / "stock" / self.stock_main
        return Path(data_dir) / "boxes" / self.id / "stock" / self.stock_main

    def to_api(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "picture": self.picture}


def _toml(path: Path, where: str) -> dict:
    if not path.is_file():
        raise ProfileError(f"{where}: missing {path.name}")
    try:
        return tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ProfileError(f"{where}/{path.name}: {exc}") from exc


def _need(d: dict, key: str, where: str) -> Any:
    if key not in d:
        raise ProfileError(f"{where}: missing {key}")
    return d[key]


def _load_items(box_dir: Path, kind: str, where: str) -> dict[str, Behaviour]:
    folder = box_dir / f"{kind}s"
    items: dict[str, Behaviour] = {}
    if not folder.is_dir():
        return items
    for meta_path in sorted(folder.glob("*.toml")):
        w = f"{where}/{kind}s/{meta_path.name}"
        meta = _toml(meta_path, w)
        bid = _need(meta, "id", w)
        if bid != meta_path.stem:
            raise ProfileError(f"{w}: id {bid!r} does not match file name")
        sketch_dir = folder / bid
        main = sketch_dir / f"{bid}.ino"
        if not main.is_file():
            raise ProfileError(f"{w}: missing sketch {bid}/{bid}.ino")
        try:
            tweakables = find_tweakables(main.read_text())
        except TemplateError as exc:
            raise ProfileError(f"{w}: {bid}.ino marker error: {exc}") from exc
        items[bid] = Behaviour(
            id=bid,
            kind=kind,
            title=_need(meta, "title", w),
            description=_need(meta, "description", w),
            sketch_dir=sketch_dir,
            tweakables=tweakables,
            tested=str(meta.get("tested", "")),
            trigger=meta.get("trigger", ""),
            action=meta.get("action", ""),
            concepts=list(meta.get("concepts", [])),
        )
    return items


def load_box(box_dir: Path, whitelist: Path | None = None) -> Box:
    where = f"boxes/{box_dir.name}"
    prof = _toml(box_dir / "profile.toml", where)
    bid = _need(prof, "id", where + "/profile.toml")
    if bid != box_dir.name:
        raise ProfileError(
            f"{where}/profile.toml: id {bid!r} does not match directory {box_dir.name!r}"
        )
    board = _need(prof, "board", where + "/profile.toml")
    stock = _need(prof, "stock", where + "/profile.toml")
    if stock.get("location") not in ("repo", "device"):
        raise ProfileError(f"{where}/profile.toml: stock.location must be 'repo' or 'device'")
    libs = list(prof.get("libraries", []))
    allowed = _whitelist(whitelist or DEFAULT_WHITELIST)
    for lib in libs:
        if lib.split("@")[0] not in allowed:
            raise ProfileError(
                f"{where}/profile.toml: library {lib} is not in provisioning/libraries.txt"
            )
    pins_doc = _toml(box_dir / "pins.toml", where)
    pins = {k: v for k, v in pins_doc.get("pins", {}).items()}
    for k, v in pins.items():
        if not isinstance(v, int) or not 0 <= v <= MAX_PIN:
            raise ProfileError(
                f"{where}/pins.toml: pin {k} = {v!r} is not a pin number 0-{MAX_PIN}"
            )
    hw = box_dir / "hardware.md"
    if not hw.is_file():
        raise ProfileError(f"{where}: missing hardware.md")
    concepts_doc = _toml(box_dir / "concepts.toml", where)
    concepts = {
        cid: Concept(
            cid,
            _need(c, "title", f"{where}/concepts.toml [{cid}]"),
            _need(c, "explanation", f"{where}/concepts.toml [{cid}]"),
            list(c.get("tags", [])),
        )
        for cid, c in concepts_doc.items()
    }
    behaviours = _load_items(box_dir, "behaviour", where)
    templates = _load_items(box_dir, "template", where)
    for b in list(behaviours.values()) + list(templates.values()):
        for c in b.concepts:
            if c not in concepts:
                raise ProfileError(f"{where}/{b.kind}s/{b.id}.toml: unknown concept {c!r}")
    if stock["location"] == "repo":
        main = box_dir / "stock" / stock["main"] / f"{stock['main']}.ino"
        if not main.is_file():
            raise ProfileError(f"{where}: missing stock sketch {main.relative_to(box_dir)}")
    return Box(
        id=bid,
        name=_need(prof, "name", where + "/profile.toml"),
        picture=prof.get("picture", f"/static/boxes/{bid}.svg"),
        root=box_dir,
        fqbn=_need(board, "fqbn", where + "/profile.toml [board]"),
        core=board.get("core", "arduino:avr"),
        libraries=libs,
        stock_location=stock["location"],
        stock_main=_need(stock, "main", where + "/profile.toml [stock]"),
        pins=pins,
        limits=dict(pins_doc.get("limits", {})),
        hardware_md=hw.read_text(),
        behaviours=behaviours,
        templates=templates,
        concepts=concepts,
    )


def load_boxes(root: Path | str = DEFAULT_BOXES, whitelist: Path | None = None) -> dict[str, Box]:
    root = Path(root)
    boxes = {}
    for d in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("_")):
        boxes[d.name] = load_box(d, whitelist)
    return boxes


def _whitelist(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    return {
        ln.strip().split("@")[0]
        for ln in path.read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    }
