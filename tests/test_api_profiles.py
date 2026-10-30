"""The API serves boxes, behaviours and concepts from profiles and flashes rendered sketches."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hacklab.app import create_app
from hacklab.board import FakeBoard
from hacklab.config import Config
from hacklab.jobs import TERMINAL_STATES


@pytest.fixture
def fb() -> FakeBoard:
    return FakeBoard()


@pytest.fixture
def client(tmp_path: Path, boxes_dir: Path, fb: FakeBoard):
    cfg = Config(data_dir=tmp_path / "data", fake_board=False, boxes_dir=boxes_dir)
    with TestClient(create_app(cfg, board=fb)) as c:
        yield c


def settle(client: TestClient, job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["state"] in TERMINAL_STATES:
            return j
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_boxes_behaviours_concepts_come_from_disk(client):
    assert client.get("/api/boxes").json() == [
        {"id": "testbox", "name": "Test Box", "picture": "/static/boxes/testbox.svg"}
    ]
    assert client.get("/api/behaviours").status_code == 409  # no box picked
    client.post("/api/box", json={"id": "testbox"})
    bh = client.get("/api/behaviours").json()
    assert [b["id"] for b in bh] == ["shake"]
    assert bh[0]["tweakables"][0]["name"] == "shakes"
    assert client.get("/api/concepts/servo").json()["title"] == "What is a servo?"
    assert client.get("/api/concepts/nope").status_code == 404
    assert client.post("/api/box", json={"id": "nope"}).status_code == 404


def test_baseline_is_the_profile_stock_sketch(client):
    client.post("/api/box", json={"id": "testbox"})
    cur = client.get("/api/sketch/current").json()
    assert cur["version"] == "0000" and cur["source"] == "void setup(){} void loop(){}\n"


def test_flash_behaviour_renders_tweakables_then_flashes(client, fb):
    client.post("/api/box", json={"id": "testbox"})
    r = client.post(
        "/api/flash/behaviour", json={"id": "shake", "tweakables": {"shakes": 7, "speed": 999}}
    )
    assert settle(client, r.json()["job_id"])["state"] == "done"
    assert "int shakes = 7;" in fb.last_uploaded_source
    assert "int speed = 90;" in fb.last_uploaded_source  # clamped
    cur = client.get("/api/sketch/current").json()
    assert cur["version"] == "0001" and "int shakes = 7;" in cur["source"]


def test_flash_behaviour_rejects_unknown_id_and_bad_tweakable(client):
    client.post("/api/box", json={"id": "testbox"})
    assert client.post("/api/flash/behaviour", json={"id": "nope"}).status_code == 404
    assert (
        client.post(
            "/api/flash/behaviour", json={"id": "shake", "tweakables": {"zzz": 1}}
        ).status_code
        == 422
    )


def test_flash_template_with_values(client, fb):
    client.post("/api/box", json={"id": "testbox"})
    r = client.post("/api/flash/template", json={"template_id": "wave", "values": {"fast": "true"}})
    assert settle(client, r.json()["job_id"])["state"] == "done"
    assert "bool fast = true;" in fb.last_uploaded_source
    assert (
        client.post("/api/flash/template", json={"template_id": "nope", "values": {}}).status_code
        == 404
    )


def test_mock_mode_still_serves_profiles(boxes_dir: Path, tmp_path: Path):
    cfg = Config(data_dir=tmp_path / "data", fake_board=True, boxes_dir=boxes_dir)
    with TestClient(create_app(cfg)) as c:
        assert [b["id"] for b in c.get("/api/boxes").json()] == ["testbox"]
        c.post("/api/box", json={"id": "testbox"})
        assert c.get("/api/behaviours").json()[0]["id"] == "shake"
        assert c.get("/api/sketch/current").json()["version"] == "stock"
