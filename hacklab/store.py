"""Per-box sketch version store on disk (STRATEGY.md P1).

data/<box>/versions/<NNNN>/<sketch>/   a copy of the sketch directory, name kept
data/<box>/versions/<NNNN>/meta.json   version metadata (outside the sketch dir)
data/<box>/current                     text file holding the current version id
arduino-cli requires <sketch>/<sketch>.ino, so the directory name is preserved.
Version 0000 is the pinned baseline (the box's stock sketch). Undo pops the
last version; Reset truncates back to 0000. Nothing here touches hardware.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path

BASELINE = "0000"


@dataclass(frozen=True)
class Version:
    id: str
    kind: str
    created: int
    sha256: str
    parent: str | None = None
    note: str = ""


def _digest(sketch_dir: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(p for p in sketch_dir.rglob("*") if p.is_file()):
        h.update(f.relative_to(sketch_dir).as_posix().encode())
        h.update(f.read_bytes())
    return h.hexdigest()


class SketchStore:
    def __init__(self, data_dir: Path | str):
        self.root = Path(data_dir)

    # -- paths -----------------------------------------------------------
    def _box(self, box: str) -> Path:
        return self.root / box

    def _versions_dir(self, box: str) -> Path:
        return self._box(box) / "versions"

    def path(self, box: str, version: Version) -> Path:
        """The sketch directory inside a version (the one arduino-cli compiles)."""
        vdir = self._versions_dir(box) / version.id
        return next(p for p in vdir.iterdir() if p.is_dir())

    def _vdir(self, box: str, version: Version) -> Path:
        return self._versions_dir(box) / version.id

    def version_dir(self, box: str, version: Version) -> Path:
        """The version folder (meta.json, fragments.json live here, beside the sketch dir)."""
        return self._vdir(box, version)

    # -- reads -----------------------------------------------------------
    def versions(self, box: str) -> list[Version]:
        d = self._versions_dir(box)
        if not d.is_dir():
            return []
        return [self._read(d / v) for v in sorted(p.name for p in d.iterdir() if p.is_dir())]

    def current(self, box: str) -> Version | None:
        f = self._box(box) / "current"
        if not f.is_file():
            return None
        return self._read(self._versions_dir(box) / f.read_text().strip())

    def previous(self, box: str) -> Version | None:
        vs = self.versions(box)
        return vs[-2] if len(vs) >= 2 else None

    def baseline(self, box: str) -> Version | None:
        d = self._versions_dir(box) / BASELINE
        return self._read(d) if d.is_dir() else None

    def main_source(self, box: str, version: Version) -> str:
        d = self.path(box, version)
        inos = sorted(d.glob("*.ino"))
        return inos[0].read_text() if inos else ""

    # -- writes ----------------------------------------------------------
    def ensure_baseline(self, box: str, sketch_dir: Path) -> Version:
        return self.baseline(box) or self._write(box, BASELINE, sketch_dir, "baseline", None, "")

    def save(self, box: str, sketch_dir: Path, kind: str, note: str = "") -> Version:
        vs = self.versions(box)
        if not vs:
            raise ValueError(f"box {box!r} has no baseline; call ensure_baseline first")
        vid = f"{int(vs[-1].id) + 1:04d}"
        return self._write(box, vid, sketch_dir, kind, vs[-1].id, note)

    def pop(self, box: str) -> Version | None:
        vs = self.versions(box)
        if len(vs) < 2:
            return self.current(box)
        shutil.rmtree(self._vdir(box, vs[-1]))
        self._set_current(box, vs[-2].id)
        return vs[-2]

    def truncate_to_baseline(self, box: str) -> Version:
        for v in self.versions(box)[1:]:
            shutil.rmtree(self._vdir(box, v))
        self._set_current(box, BASELINE)
        return self.baseline(box)

    # -- internals -------------------------------------------------------
    def _write(self, box, vid, sketch_dir, kind, parent, note) -> Version:
        vdir = self._versions_dir(box) / vid
        vdir.mkdir(parents=True, exist_ok=True)
        dest = vdir / Path(sketch_dir).name  # keep the name: arduino-cli wants <dir>/<dir>.ino
        shutil.copytree(sketch_dir, dest)
        v = Version(
            id=vid,
            kind=kind,
            created=int(time.time()),
            sha256=_digest(dest),
            parent=parent,
            note=note,
        )
        (vdir / "meta.json").write_text(json.dumps(asdict(v)))
        self._set_current(box, vid)
        return v

    def _read(self, d: Path) -> Version:
        return Version(**json.loads((d / "meta.json").read_text()))

    def _set_current(self, box: str, vid: str) -> None:
        (self._box(box) / "current").write_text(vid)
