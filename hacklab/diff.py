"""What just changed: a unified diff between two sketch directories (every *.ino and *.h),
so the AI helper can explain the code that was added or removed (P8 round 5)."""

from __future__ import annotations

import difflib
from pathlib import Path

SOURCE_SUFFIXES = (".ino", ".h", ".hpp")


def sketch_diff(before: Path, after: Path, context: int = 2) -> str:
    """Unified diff of `before` -> `after`, file by file; "" when nothing differs."""
    names = sorted(
        {
            p.name
            for d in (before, after)
            if d.is_dir()
            for p in d.iterdir()
            if p.suffix in SOURCE_SUFFIXES
        },
        key=lambda n: (not n.endswith(".ino"), n),
    )
    out: list[str] = []
    for name in names:
        a = (before / name).read_text().splitlines() if (before / name).is_file() else []
        b = (after / name).read_text().splitlines() if (after / name).is_file() else []
        if a == b:
            continue
        out.extend(
            difflib.unified_diff(a, b, f"before/{name}", f"after/{name}", lineterm="", n=context)
        )
    return "\n".join(out)
