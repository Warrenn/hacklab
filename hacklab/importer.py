"""Hack Pack IDE importer (P6): an editor dump -> a box profile.

Input is the JSON written by scripts/import-box.js: {"slug", "files": {"<Dir>/<file>": text}}.
MIT-headed stock dirs are committed under boxes/<id>/stock/; anything else is staged for
the device (never in git). The rest of the profile is scaffolded from boxes/_template and
derived from the main sketch (pins, markers, genie skeleton). Hand-edited files are kept.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from hacklab.templates import TemplateError, find_tweakables

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
DEFINE = re.compile(r"^\s*#define\s+([A-Za-z_]\w*)\s+(\d{1,2})\b")
_TYPES = "int|long|double|float|bool|char|byte|uint8_t|uint16_t|uint32_t|unsigned long|Servo"
GLOBAL = re.compile(rf"^(?:const\s+|unsigned\s+|static\s+)*(?:{_TYPES})\b[^(]*;")
PRAGMA_FUNCS_END = "#pragma endregion FUNCTIONS"
IR_SWITCH = "switch(IrReceiver.decodedIRData.command){"


@dataclass
class Report:
    box: str
    license: dict[str, str] = field(default_factory=dict)  # stock dir -> "MIT" | "none"
    written: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    staged: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"box {self.box}: " + ", ".join(f"{d}={lic}" for d, lic in self.license.items())]
        lines += [f"  wrote  {p}" for p in self.written]
        lines += [f"  kept   {p}" for p in self.kept]
        lines += [f"  staged {p} (device only: no license header)" for p in self.staged]
        return "\n".join(lines)


def is_mit(source: str) -> bool:
    head = source[:4000]
    return "MIT License" in head and "Copyright" in head


def place_markers(source: str) -> str:
    """Insert the four genie markers into a stock sketch (see STRATEGY.md P6 plan)."""
    lines = source.split("\n")
    out: list[str] = []
    setup_at = next((i for i, ln in enumerate(lines) if ln.startswith("void setup()")), len(lines))
    last_global = max(
        (i for i in range(setup_at) if GLOBAL.match(lines[i]) and not lines[i].startswith("void")),
        default=-1,
    )
    ir_switch = next((i for i, ln in enumerate(lines) if IR_SWITCH in ln), None)
    switch_end = None
    if (
        ir_switch is not None
    ):  # the switch closes at the first line that is exactly "<indent>}" with the switch's indent
        indent = len(lines[ir_switch]) - len(lines[ir_switch].lstrip())
        switch_end = next(
            i for i in range(ir_switch + 1, len(lines)) if lines[i] == " " * indent + "}"
        )
    loop_at = next((i for i, ln in enumerate(lines) if ln.startswith("void loop()")), None)
    funcs_end = next((i for i, ln in enumerate(lines) if ln.strip() == PRAGMA_FUNCS_END), None)
    body_indent = "    " if ir_switch is not None else "  "
    for i, ln in enumerate(lines):
        if i == switch_end:
            out.append(" " * (len(ln) - len(ln.lstrip()) + 4) + "//@@CASES")
        if i == funcs_end:
            out.append("//@@FUNCTIONS")
        out.append(ln)
        if i == last_global:
            out.append("//@@PARAMS")
        if i == loop_at:
            out.append(body_indent + "//@@LOOP")
            if switch_end is None:
                out.append(body_indent + "//@@CASES")
    if last_global == -1:
        out.insert(setup_at, "//@@PARAMS")
    if funcs_end is None:  # no FUNCTIONS region: append at the end of file
        while out and not out[-1].strip():
            out.pop()
        out += ["//@@FUNCTIONS", ""]
    # ponytail: line heuristics; an odd layout gets its skeleton hand-tuned (STRATEGY.md P6)
    return "\n".join(out)


def _pins(main: str, others: dict[str, str]) -> str:
    pins = [
        (m.group(1), int(m.group(2)))
        for m in map(DEFINE.match, main.splitlines())
        if m and int(m.group(2)) <= 21
    ]
    body = (
        "# Derived by scripts/import-box.sh from the stock sketch; check against the box.\n[pins]\n"
    )
    body += "".join(f"{name.lower()} = {num}\n" for name, num in pins)
    limits = []
    for text in [main, *others.values()]:
        try:
            limits += [t for t in find_tweakables(text) if t.range or t.options]
        except TemplateError:
            continue
    body += "\n[limits]\n" + "".join(
        f"{t.name} = {{ min = {t.range[0]:g}, max = {t.range[1]:g} }}\n"
        if t.range
        else f"{t.name} = {{ options = {t.options!r} }}\n"
        for t in limits
    ).replace("'", '"')
    return body


def _hardware(box_id: str, main: str) -> str:
    rows = [(m.group(1), m.group(2)) for m in map(DEFINE.match, main.splitlines()) if m]
    table = (
        "| Name | Pin |\n| --- | --- |\n" + "".join(f"| {n} | {p} |\n" for n, p in rows)
        if rows
        else "(no #define pins found)\n"
    )
    todo = "TODO: describe every actuator, sensor and input in kid words, with safe ranges."
    return f"# {box_id} — hardware\n\n{todo}\n\n{table}"


def _write(path: Path, text: str, rep: Report, rel: str, keep: bool = True) -> None:
    if keep and path.exists():
        rep.kept.append(rel)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    rep.written.append(rel)


def import_box(
    dump: dict,
    repo_boxes: Path,
    device_staging: Path,
    fqbn: str = "arduino:avr:nano",
    name: str | None = None,
) -> Report:
    slug = str(dump.get("slug", ""))
    if not SLUG.match(slug):
        raise ValueError(f"bad slug {slug!r}")
    files: dict[str, str] = dump.get("files") or {}
    dirs: dict[str, dict[str, str]] = {}
    for rel, text in files.items():
        d, _, fn = rel.partition("/")
        if d and fn:
            dirs.setdefault(d, {})[fn] = text
    mains = {d: fs[f"{d}.ino"] for d, fs in dirs.items() if f"{d}.ino" in fs}
    if not mains:
        raise ValueError("no <Dir>/<Dir>.ino sketch in the dump")
    rep = Report(slug)
    repo_boxes, device_staging = Path(repo_boxes), Path(device_staging)
    box = repo_boxes / slug
    # stock dirs: verbatim, every run
    for d, fs in dirs.items():
        if d not in mains:
            continue
        mit = is_mit(mains[d])
        rep.license[d] = "MIT" if mit else "none"
        base = box / "stock" if mit else device_staging / slug / "stock"
        for fn, text in fs.items():
            _write(
                base / d / fn,
                text,
                rep,
                f"{slug}/stock/{d}/{fn}" if mit else f"{slug}/stock/{d}/{fn}",
                keep=False,
            )
            if not mit:
                rep.staged.append(rep.written.pop())
    main_dir = "stock" if "stock" in mains else sorted(mains)[0]
    location = "repo" if rep.license[main_dir] == "MIT" else "device"
    main_src = mains[main_dir]
    core = fqbn.rsplit(":", 1)[0]
    pretty = name or slug.replace("-", " ").title()
    _write(
        box / "profile.toml",
        f"# Imported by scripts/import-box.sh from the Hack Pack IDE ({slug}).\n"
        "# Edit freely; re-runs keep this file.\n"
        f'id = "{slug}"\nname = "{pretty}"\npicture = "/static/boxes/{slug}.svg"\n'
        "libraries = []\n\n"
        f'[board]\nfqbn = "{fqbn}"\ncore = "{core}"\n\n'
        f'[stock]\nlocation = "{location}"\nmain = "{main_dir}"\n\n'
        f'[genie]\nskeleton = "genie/skeleton.ino"\nhelpers = []\nkeys = []\n',
        rep,
        f"{slug}/profile.toml",
    )
    _write(
        box / "pins.toml",
        _pins(main_src, {k: v for k, v in dirs[main_dir].items() if k != f"{main_dir}.ino"}),
        rep,
        f"{slug}/pins.toml",
    )
    _write(box / "hardware.md", _hardware(slug, main_src), rep, f"{slug}/hardware.md")
    _write(
        box / "concepts.toml",
        "# [concept-id]  title, explanation (kid language, no links), tags, question\n",
        rep,
        f"{slug}/concepts.toml",
    )
    for sub in ("behaviours", "templates"):
        (box / sub).mkdir(parents=True, exist_ok=True)
    skel_base = box if location == "repo" else device_staging / slug
    skel_rel = f"{slug}/genie/skeleton.ino"
    skel = skel_base / "genie" / "skeleton.ino"
    if location == "repo":
        _write(skel, place_markers(main_src), rep, skel_rel)
    else:
        skel.parent.mkdir(parents=True, exist_ok=True)
        skel.write_text(place_markers(main_src))
        rep.staged.append(skel_rel)
    return rep


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser(description="editor dump -> box profile")
    ap.add_argument("dump")
    ap.add_argument("--boxes", default=str(Path(__file__).resolve().parent.parent / "boxes"))
    ap.add_argument(
        "--staging",
        default=str(Path(__file__).resolve().parent.parent / "provisioning" / "local" / "boxes"),
    )
    ap.add_argument("--fqbn", default="arduino:avr:nano")
    ap.add_argument("--name")
    a = ap.parse_args(argv)
    rep = import_box(
        json.loads(Path(a.dump).read_text()),
        Path(a.boxes),
        Path(a.staging),
        fqbn=a.fqbn,
        name=a.name,
    )
    print(rep.summary(), file=sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
