"""hacklab ops agent: report-only heartbeat to the AWS IoT device shadow.

Publishes `reported` state every INTERVAL seconds over mutual-TLS MQTT. It
subscribes to nothing and executes nothing (STRATEGY.md P5a). Stdlib plus
awsiotsdk; runs from its own venv as hacklab-ops.service.

Env: HACKLAB_THING, HACKLAB_IOT_ENDPOINT, HACKLAB_IOT_DIR (cert.pem,
private.key, AmazonRootCA1.pem), HACKLAB_OPS_INTERVAL (s, default 300).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

VERSION = "0.1.0"
HOTSPOT_PREFIX = "hacklab-setup"
log = logging.getLogger("hacklab-ops")

Runner = Callable[[list[str]], str]


def run_cmd(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=True).stdout


def _try(fn: Callable[[], object]):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - a missing tool must never kill the heartbeat
        log.debug("collector skipped: %s", exc)
        return None


def _wifi(run: Runner) -> dict | None:
    line = next(
        ln
        for ln in run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "dev"]).splitlines()
        if ln.startswith("wlan0:")
    )
    conn = line.split(":", 3)[3]
    ip = _try(
        lambda: json.loads(run(["ip", "-j", "-4", "addr", "show", "wlan0"]))[0]["addr_info"][0][
            "local"
        ]
    )
    return {"ssid": conn, "ip": ip, "hotspot": conn.startswith(HOTSPOT_PREFIX)}


def collect_state(run: Runner = run_cmd, root: Path = Path("/")) -> dict:
    """Everything status.sh shows. Each field is None when unavailable."""
    current = root / "opt/hacklab/current"
    return {
        "ts": int(time.time()),
        "agent": VERSION,
        "hostname": _try(lambda: run(["hostname"]).strip()),
        "uptime_s": _try(lambda: int(float((root / "proc/uptime").read_text().split()[0]))),
        "cpu_temp_c": _try(
            lambda: round(
                int((root / "sys/class/thermal/thermal_zone0/temp").read_text()) / 1000, 1
            )
        ),
        "disk_free_mb": _try(lambda: shutil.disk_usage(root).free // 2**20),
        "release": current.resolve().name if current.is_symlink() else "none",
        "wifi": _try(lambda: _wifi(run)),
        "tailscale_ip": _try(lambda: run(["tailscale", "ip", "-4"]).split()[0]),
    }


def shadow_topic(thing: str) -> str:
    return f"$aws/things/{thing}/shadow/update"


def shadow_payload(state: dict) -> bytes:
    return json.dumps({"state": {"reported": state}}).encode()


class Heartbeat:
    def __init__(self, client, thing: str, collect: Callable[[], dict] = collect_state):
        self.client, self.topic, self.collect = client, shadow_topic(thing), collect

    def tick(self) -> bool:
        try:
            self.client.publish(self.topic, shadow_payload(self.collect()))
            return True
        except Exception as exc:  # noqa: BLE001 - log and try again next interval
            log.warning("heartbeat failed: %s", exc)
            return False

    def run(self, interval: float) -> None:
        while True:
            self.tick()
            time.sleep(interval)


class MqttClient:
    """Thin adapter so the agent only needs publish(topic, bytes)."""

    def __init__(self, endpoint: str, iot_dir: Path, client_id: str):
        from awscrt import mqtt
        from awsiot import mqtt_connection_builder

        self.qos = mqtt.QoS.AT_LEAST_ONCE
        self.conn = mqtt_connection_builder.mtls_from_path(
            endpoint=endpoint,
            cert_filepath=str(iot_dir / "cert.pem"),
            pri_key_filepath=str(iot_dir / "private.key"),
            ca_filepath=str(iot_dir / "AmazonRootCA1.pem"),
            client_id=client_id,
            clean_session=False,
            keep_alive_secs=60,
        )
        self.conn.connect().result(timeout=30)  # the SDK reconnects on its own after this

    def publish(self, topic: str, payload: bytes) -> None:
        self.conn.publish(topic=topic, payload=payload, qos=self.qos)[0].result(timeout=30)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stdout)
    thing = os.environ["HACKLAB_THING"]
    client = MqttClient(
        endpoint=os.environ["HACKLAB_IOT_ENDPOINT"],
        iot_dir=Path(os.environ.get("HACKLAB_IOT_DIR", "/opt/hacklab/data/iot")),
        client_id=thing or socket.gethostname(),
    )
    log.info("connected as %s", thing)
    Heartbeat(client, thing).run(float(os.environ.get("HACKLAB_OPS_INTERVAL", "300")))


if __name__ == "__main__":
    main()
