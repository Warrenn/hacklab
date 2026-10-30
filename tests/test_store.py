"""Per-box sketch version store: persistent, baseline pinned, directories."""

from pathlib import Path

import pytest

from hacklab.store import SketchStore


def sketch(tmp_path: Path, name: str, body: str, extra: dict[str, str] | None = None) -> Path:
    d = tmp_path / name
    d.mkdir()
    (d / f"{name}.ino").write_text(body)
    for fn, txt in (extra or {}).items():
        (d / fn).write_text(txt)
    return d


@pytest.fixture
def store(tmp_path: Path) -> SketchStore:
    return SketchStore(tmp_path / "data")


def test_baseline_is_version_0000_and_current(store: SketchStore, tmp_path: Path):
    v = store.ensure_baseline("ir-turret", sketch(tmp_path, "stock", "void loop(){}"))
    assert v.id == "0000"
    assert v.kind == "baseline"
    assert store.current("ir-turret").id == "0000"
    assert (store.path("ir-turret", v) / "stock.ino").read_text() == "void loop(){}"


def test_ensure_baseline_is_idempotent(store: SketchStore, tmp_path: Path):
    s = sketch(tmp_path, "stock", "a")
    store.ensure_baseline("b", s)
    store.save("b", sketch(tmp_path, "one", "b"), kind="flash")
    store.ensure_baseline("b", s)  # must not reset anything
    assert [v.id for v in store.versions("b")] == ["0000", "0001"]


def test_save_copies_multi_file_dir_and_advances(store: SketchStore, tmp_path: Path):
    store.ensure_baseline("b", sketch(tmp_path, "stock", "a"))
    v = store.save(
        "b", sketch(tmp_path, "s", "void loop(){}", {"config.h": "int x;"}), kind="flash"
    )
    assert v.id == "0001" and v.parent == "0000"
    assert (store.path("b", v) / "config.h").read_text() == "int x;"
    assert store.current("b").id == "0001"
    assert v.sha256 and len(v.sha256) == 64


def test_versions_survive_a_new_store_instance(tmp_path: Path):
    s1 = SketchStore(tmp_path / "data")
    s1.ensure_baseline("b", sketch(tmp_path, "stock", "a"))
    s1.save("b", sketch(tmp_path, "s", "b"), kind="ask", note="make it spin")
    s2 = SketchStore(tmp_path / "data")
    assert [v.id for v in s2.versions("b")] == ["0000", "0001"]
    assert s2.current("b").note == "make it spin"


def test_previous_and_pop(store: SketchStore, tmp_path: Path):
    store.ensure_baseline("b", sketch(tmp_path, "stock", "a"))
    assert store.previous("b") is None  # nothing to undo at baseline
    store.save("b", sketch(tmp_path, "s1", "1"), kind="flash")
    store.save("b", sketch(tmp_path, "s2", "2"), kind="flash")
    assert store.previous("b").id == "0001"
    store.pop("b")
    assert store.current("b").id == "0001"
    assert [v.id for v in store.versions("b")] == ["0000", "0001"]
    assert not (store.path("b", store.current("b")).parent / "0002").exists()


def test_pop_never_removes_baseline(store: SketchStore, tmp_path: Path):
    store.ensure_baseline("b", sketch(tmp_path, "stock", "a"))
    store.pop("b")
    assert store.current("b").id == "0000"


def test_truncate_to_baseline(store: SketchStore, tmp_path: Path):
    store.ensure_baseline("b", sketch(tmp_path, "stock", "a"))
    for i in range(3):
        store.save("b", sketch(tmp_path, f"s{i}", str(i)), kind="flash")
    store.truncate_to_baseline("b")
    assert [v.id for v in store.versions("b")] == ["0000"]
    assert store.current("b").id == "0000"


def test_boxes_are_independent(store: SketchStore, tmp_path: Path):
    store.ensure_baseline("a", sketch(tmp_path, "sa", "a"))
    store.ensure_baseline("b", sketch(tmp_path, "sb", "b"))
    store.save("a", sketch(tmp_path, "s1", "1"), kind="flash")
    assert len(store.versions("a")) == 2 and len(store.versions("b")) == 1


def test_main_source(store: SketchStore, tmp_path: Path):
    store.ensure_baseline("b", sketch(tmp_path, "stock", "void loop(){}", {"config.h": "x"}))
    assert store.main_source("b", store.current("b")) == "void loop(){}"


def test_unknown_box_has_no_current(store: SketchStore):
    assert store.current("nope") is None
    assert store.versions("nope") == []


def test_stored_sketch_dir_keeps_its_name_for_arduino_cli(store: SketchStore, tmp_path: Path):
    v = store.ensure_baseline("b", sketch(tmp_path, "StockCode", "x", {"config.h": "y"}))
    d = store.path("b", v)
    assert d.name == "StockCode" and (d / "StockCode.ino").is_file() and (d / "config.h").is_file()
    assert not (d / "meta.json").exists()  # meta lives beside the sketch dir, not inside it
    v1 = store.save("b", sketch(tmp_path, "blink", "z"), kind="flash")
    assert store.path("b", v1).name == "blink"
