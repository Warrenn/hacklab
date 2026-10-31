"""P8 round 7: the event stream sends ping events the page can time, so a dead stream on a
phone is noticed and reconnected (a comment keep-alive is invisible to EventSource)."""

import json

from fastapi.testclient import TestClient

from hacklab.app import create_app
from hacklab.config import Config


def test_the_event_stream_sends_visible_pings(tmp_path, boxes_dir):
    cfg = Config(data_dir=tmp_path / "data", fake_board=True, boxes_dir=boxes_dir, sse_ping=0.1)
    with TestClient(create_app(cfg)) as c, c.stream("GET", "/api/events") as r:
        for line in r.iter_lines():
            if line.startswith("data:"):
                assert json.loads(line[5:])["type"] == "ping"
                break
