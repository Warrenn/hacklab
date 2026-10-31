"""What just changed: a unified diff between two sketch directories (every *.ino and *.h),
so the AI helper can explain the code that was added or removed (P8 round 5)."""

from __future__ import annotations

import difflib
from pathlib import Path

SOURCE_SUFFIXES = (".ino", ".h", ".hpp")


def _sources(d: Path) -> dict[str, Path]:
    """The files of a sketch dir keyed by role: the one main `.ino` is "main" (its name differs
    between the stock, a trick and the AI helper's sketch), every other source by its name."""
    if not d.is_dir():
        return {}
    files = sorted(p for p in d.iterdir() if p.suffix in SOURCE_SUFFIXES)
    inos = [p for p in files if p.suffix == ".ino"]
    out = {"main": inos[0]} if inos else {}
    out.update({p.name: p for p in files if p not in inos[:1]})
    return out


def sketch_diff(before: Path, after: Path, context: int = 2) -> str:
    """Unified diff of `before` -> `after`, the main sketch paired by role and the other
    files by name; "" when nothing differs."""
    a_files, b_files = _sources(before), _sources(after)
    keys = sorted(set(a_files) | set(b_files), key=lambda k: (k != "main", k))
    out: list[str] = []
    for key in keys:
        pa, pb = a_files.get(key), b_files.get(key)
        a = pa.read_text().splitlines() if pa else []
        b = pb.read_text().splitlines() if pb else []
        if a == b:
            continue
        label = (pb or pa).name if key != "main" else f"{(pa or pb).name}"
        after_label = pb.name if pb else label
        out.extend(
            difflib.unified_diff(
                a, b, f"before/{label}", f"after/{after_label}", lineterm="", n=context
            )
        )
    return "\n".join(out)
