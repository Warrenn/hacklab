"""The review copy of the PWA: the real page plus an in-page stand-in for the API,
built from the real box data, publishable as a standalone artifact."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from hacklab import preview

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def html() -> str:
    return preview.build(ROOT)


def test_document_shell_is_stripped_and_assets_are_relative(html):
    assert "<!doctype" not in html.lower() and "</html>" not in html and "<body>" not in html
    assert "/static/" not in html  # the artifact serves files next to the page
    assert "static/boxes/" in html and "static/icon.svg" in html
    assert "<title>Hack Lab Preview</title>" in html
    assert "serviceWorker" not in html


def test_real_box_data_is_embedded(html):
    assert "__HACKLAB_PREVIEW__" in html
    for box in ("ir-turret", "omnibot-forklift", "synthesizer"):
        assert f'"id": "{box}"' in html
    assert "Make it play a minor scale" in html  # synth ask placeholder from profile.toml
    assert "shake-head" in html and "Turning the code into robot language." in html
    assert "lives only on the device" in html  # Forklift stock placeholder, not CrunchLabs code


def test_page_code_itself_is_untouched(html):
    page = (ROOT / "static" / "index.html").read_text()
    start = page.index("'use strict';")
    app_js = page[start : page.index("</script>", start)]
    app_js = app_js.replace("/static/", "static/")
    app_js = re.sub(r"\n\s*if \('serviceWorker' in navigator.*\n", "\n", app_js)
    assert app_js in html


def test_ribbon_marks_it_as_a_preview(html):
    assert "pretend board" in html


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_stand_in_script_parses(html, tmp_path: Path):
    shim = re.search(r"<script id=\"preview-api\">(.*?)</script>", html, re.S).group(1)
    f = tmp_path / "shim.js"
    f.write_text(shim)
    subprocess.run(["node", "--check", str(f)], check=True)
