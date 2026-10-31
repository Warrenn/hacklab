"""Review copy of the PWA for the owner to comment on (STRATEGY "UI review loop").

`build(root)` returns static/index.html with the document shell stripped (the
artifact host adds its own), `/static/` made relative, a thin "Preview" ribbon,
and an in-page stand-in for the API: `fetch('/api/...')` and `EventSource` are
replaced by a script that carries the real box data from boxes/ and walks jobs
through the real stage names and kid messages on a timer, like the mock backend.
The page's own code is left untouched. `python -m hacklab.preview` writes
dist/preview/index.html.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from hacklab.jobs import MESSAGES
from hacklab.profiles import load_boxes
from hacklab.templates import TemplateError, find_tweakables

DEVICE_ONLY = (
    "// This box's stock code is not MIT-licensed, so it lives only on the device.\n"
    "// (Preview stand-in; the real page shows the real code.)\n"
)

RIBBON = (
    '<div class="preview-ribbon">Preview copy with a pretend board and AI helper. '
    "Leave comments anywhere on the page.</div>\n"
)
RIBBON_CSS = (
    ".preview-ribbon{background:#1B1F3A;color:#fff;font:700 13px system-ui,sans-serif;"
    "text-align:center;padding:6px 16px}\n"
)


def box_data(root: Path) -> dict:
    boxes = load_boxes(root / "boxes")
    data = {}
    for b in boxes.values():
        stock = b.stock_dir(root / "data") / f"{b.stock_main}.ino"
        sketches = {}
        for item in list(b.behaviours.values()) + list(b.templates.values()):
            ino = item.sketch_dir / f"{item.id}.ino"
            if ino.is_file():
                sketches[item.id] = ino.read_text()
        files = []
        sd = b.stock_dir(root / "data")
        if sd.is_dir():
            for f in sorted(sd.glob("*.ino")) + sorted(sd.glob("*.h")):
                try:
                    tws = [t.to_api() for t in find_tweakables(f.read_text())]
                except TemplateError:
                    tws = []
                for t in tws:
                    if "label" not in t and t["name"] in b.labels:
                        t["label"] = b.labels[t["name"]]
                files.append({"name": f.name, "source": f.read_text(), "tweakables": tws})
        data[b.id] = {
            "files": files,  # Level 2 on the box's own code (the IDE's markers, per file)
            "behaviours": [x.to_api() for x in b.behaviours.values()],
            "concepts": {
                k: {**c.to_api(), "question": c.prompt_question()} for k, c in b.concepts.items()
            },
            "stock": stock.read_text() if stock.is_file() else DEVICE_ONLY,
            "sketches": sketches,
        }
    return {"boxes": [b.to_api() for b in boxes.values()], "data": data}


SHIM_JS = Path(__file__).with_name("preview_api.js")


def build(root: Path) -> str:
    page = (root / "static" / "index.html").read_text()
    # document shell: the artifact host wraps the page itself
    shell = ("<!doctype html>", '<html lang="en">', "<head>", "</head>", "<body>", "</body>")
    for tag in (*shell, "</html>"):
        page = page.replace(tag + "\n", "").replace(tag, "")
    page = page.replace("<title>Hack Lab</title>", "<title>Hack Lab Preview</title>")
    page = re.sub(r'<link rel="manifest"[^>]*>\n', "", page)
    page = re.sub(r"\n\s*if \('serviceWorker' in navigator.*\n", "\n", page)
    page = page.replace("</style>", RIBBON_CSS + "</style>", 1)
    data = json.dumps(box_data(root), indent=1)
    shim = SHIM_JS.read_text().replace("__MESSAGES__", json.dumps(MESSAGES))
    stand_in = (
        f"<script>window.__HACKLAB_PREVIEW__ = {data};</script>\n"
        f'<script id="preview-api">{shim}</script>\n'
    )
    page = page.replace('<div id="app"', RIBBON + stand_in + '<div id="app"', 1)
    return page.replace("/static/", "static/")  # the artifact serves files next to the page


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "dist" / "preview" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(root))
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
