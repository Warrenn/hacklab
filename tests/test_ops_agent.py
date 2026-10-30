"""Ops agent: state collector, shadow payload, heartbeat tick."""

import json
from pathlib import Path

import pytest

from ops import agent


def fake_run(outputs: dict[str, str]):
    """Return a runner that answers by the first word of the command."""

    def run(cmd: list[str]) -> str:
        if cmd[0] not in outputs:
            raise FileNotFoundError(cmd[0])
        return outputs[cmd[0]]

    return run


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "proc").mkdir()
    (tmp_path / "proc/uptime").write_text("12345.67 24000.00\n")
    (tmp_path / "sys/class/thermal/thermal_zone0").mkdir(parents=True)
    (tmp_path / "sys/class/thermal/thermal_zone0/temp").write_text("48312\n")
    rel = tmp_path / "opt/hacklab/releases/0.3.0"
    rel.mkdir(parents=True)
    (tmp_path / "opt/hacklab/current").symlink_to(rel)
    return tmp_path


OUTPUTS = {
    "hostname": "hacklab\n",
    "nmcli": "wlan0:wifi:connected:Home-WiFi\n",
    "ip": '[{"addr_info":[{"local":"10.0.0.23"}]}]\n',
    "tailscale": "100.64.0.7\n",
}


def test_collect_state_reads_everything(root: Path):
    st = agent.collect_state(run=fake_run(OUTPUTS), root=root)
    assert st["hostname"] == "hacklab"
    assert st["uptime_s"] == 12345
    assert st["cpu_temp_c"] == 48.3
    assert st["release"] == "0.3.0"
    assert st["wifi"] == {"ssid": "Home-WiFi", "ip": "10.0.0.23", "hotspot": False}
    assert st["tailscale_ip"] == "100.64.0.7"
    assert st["disk_free_mb"] > 0
    assert st["agent"] == agent.VERSION
    assert isinstance(st["ts"], int)


def test_hotspot_detected_from_connection_name(root: Path):
    out = dict(OUTPUTS, nmcli="wlan0:wifi:connected:hacklab-setup-0000\n")
    st = agent.collect_state(run=fake_run(out), root=root)
    assert st["wifi"]["hotspot"] is True
    assert st["wifi"]["ssid"] == "hacklab-setup-0000"


def test_missing_tools_and_files_never_raise(tmp_path: Path):
    st = agent.collect_state(run=fake_run({}), root=tmp_path)
    assert st["hostname"] is None
    assert st["uptime_s"] is None
    assert st["cpu_temp_c"] is None
    assert st["wifi"] is None
    assert st["tailscale_ip"] is None
    assert st["release"] == "none"
    json.dumps(st)  # still serialisable


def test_shadow_payload_and_topic():
    payload = agent.shadow_payload({"hostname": "hacklab"})
    assert json.loads(payload) == {"state": {"reported": {"hostname": "hacklab"}}}
    assert agent.shadow_topic("hacklab-pi3") == "$aws/things/hacklab-pi3/shadow/update"


class FakeClient:
    def __init__(self, fail: bool = False):
        self.published: list[tuple[str, bytes]] = []
        self.fail = fail

    def publish(self, topic: str, payload: bytes) -> None:
        if self.fail:
            raise ConnectionError("offline")
        self.published.append((topic, payload))


def test_tick_publishes_reported_state():
    client = FakeClient()
    hb = agent.Heartbeat(client, thing="hacklab-pi3", collect=lambda: {"hostname": "hacklab"})
    assert hb.tick() is True
    ((topic, payload),) = client.published
    assert topic == "$aws/things/hacklab-pi3/shadow/update"
    assert json.loads(payload)["state"]["reported"]["hostname"] == "hacklab"


def test_tick_survives_publish_failure():
    hb = agent.Heartbeat(FakeClient(fail=True), thing="t", collect=lambda: {})
    assert hb.tick() is False


def test_tick_survives_collector_failure():
    def boom():
        raise RuntimeError("sensor")

    client = FakeClient()
    hb = agent.Heartbeat(client, thing="t", collect=boom)
    assert hb.tick() is False
    assert client.published == []
