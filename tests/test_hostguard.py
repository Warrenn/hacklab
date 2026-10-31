"""P7b: the app answers only for its own hostnames and refuses cross-site POSTs, so a
malicious web page in the kid's browser cannot drive the box (CSRF, DNS rebinding).
Request bodies have sane size limits."""

from fastapi.testclient import TestClient

from hacklab.app import create_app
from hacklab.config import Config


def client(tmp_path, boxes_dir, **cfg):
    c = Config(data_dir=tmp_path / "data", fake_board=True, boxes_dir=boxes_dir, **cfg)
    return TestClient(create_app(c))


def test_own_hostnames_are_served(tmp_path, boxes_dir):
    with client(tmp_path, boxes_dir) as c:
        for host in (
            "hacklab.local",
            "hacklab",
            "localhost:8000",
            "10.0.0.21",
            "10.0.0.21:80",
            "hacklab.tail1234.ts.net",
            "[fd7a:115c:a1e0::1]:80",
        ):
            assert c.get("/api/status", headers={"host": host}).status_code == 200, host


def test_foreign_host_is_refused(tmp_path, boxes_dir):
    with client(tmp_path, boxes_dir) as c:
        r = c.get("/api/status", headers={"host": "evil.example.com"})
        assert r.status_code == 400
        assert c.get("/", headers={"host": "evil.example.com:80"}).status_code == 400


def test_extra_hosts_come_from_config(tmp_path, boxes_dir):
    with client(tmp_path, boxes_dir, allowed_hosts=["robots.lan"]) as c:
        assert c.get("/api/status", headers={"host": "robots.lan"}).status_code == 200


def test_cross_site_post_is_refused_but_same_site_is_fine(tmp_path, boxes_dir):
    with client(tmp_path, boxes_dir) as c:
        bad = c.post(
            "/api/box",
            json={"id": "testbox"},
            headers={"host": "hacklab.local", "origin": "http://evil.example.com"},
        )
        assert bad.status_code == 403
        ok = c.post(
            "/api/box",
            json={"id": "testbox"},
            headers={"host": "hacklab.local", "origin": "http://hacklab.local"},
        )
        assert ok.status_code == 200
        # a browser fetch from the page itself sends no Origin on GET and the same Origin on POST
        plain = c.post("/api/box", json={"id": "testbox"}, headers={"host": "hacklab"})
        assert plain.status_code == 200


def test_body_limits(tmp_path, boxes_dir):
    with client(tmp_path, boxes_dir) as c:
        c.post("/api/box", json={"id": "testbox"})
        assert c.post("/api/ask", json={"text": "x" * 501}).status_code == 422
        huge = {"source": "/" * (256 * 1024 + 1)}
        assert c.post("/api/flash/sketch", json=huge).status_code == 422
        many = {"id": "shake", "tweakables": {f"k{i}": 1 for i in range(33)}}
        assert c.post("/api/flash/behaviour", json=many).status_code == 422
