"""Genie skeleton: a box's stock sketch with //@@PARAMS, //@@CASES, //@@LOOP and
//@@FUNCTIONS insertion points. The AI helper returns only the four fragments;
assembling them into the fixed skeleton is what keeps setup, pins and
libraries out of the model's hands (STRATEGY.md P4)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

from hacklab.profiles import Box

MARKERS = ("PARAMS", "CASES", "LOOP", "FUNCTIONS")


class SkeletonError(ValueError):
    pass


@dataclass(frozen=True)
class Fragments:
    params: str = ""
    cases: str = ""
    loop: str = ""
    functions: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Fragments:
        return cls(**{k: str(d.get(k, "") or "") for k in ("params", "cases", "loop", "functions")})


def assemble(skeleton: str, f: Fragments) -> str:
    out = skeleton
    for name in MARKERS:
        m = re.search(rf"^([ \t]*)//@@{name}[ \t]*$", out, re.M)
        if not m:
            raise SkeletonError(f"skeleton has no //@@{name} marker")
        indent = m.group(1)
        text = getattr(f, name.lower()).strip("\n")
        body = (
            "\n".join(indent + ln if ln.strip() else "" for ln in text.split("\n")) if text else ""
        )
        out = out[: m.start()] + body + out[m.end() :]
    return out


def load_skeleton(box: Box, data_dir: Path) -> str | None:
    """The skeleton text, or None when the box has none (genie unavailable)."""
    rel = box.genie.get("skeleton")
    if not rel:
        return None
    base = box.root if box.stock_location == "repo" else Path(data_dir) / "boxes" / box.id
    p = base / rel
    return p.read_text() if p.is_file() else None
