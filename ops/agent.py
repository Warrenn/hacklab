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
        "release": current.resolve().name
        if current.is_symlink()
        else "none",  # "src" or the release version
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


class JobsWorker:
    """IoT Jobs (P5c): take the next pending job, run it through the allowlisted
    executor in a thread, report progress and the result. One job at a time."""

    def __init__(self, conn, thing: str, executor):
        import threading

        from awscrt import mqtt
        from awsiot import iotjobs

        self.jobs = iotjobs.IotJobsClient(conn)
        self.thing, self.executor = thing, executor
        self.iotjobs, self.qos = iotjobs, mqtt.QoS.AT_LEAST_ONCE  # the SDK asserts a QoS enum
        self._busy = threading.Lock()
        self.last: dict | None = None

    def start(self) -> None:
        j = self.iotjobs
        self.jobs.subscribe_to_next_job_execution_changed_events(
            j.NextJobExecutionChangedSubscriptionRequest(thing_name=self.thing),
            qos=self.qos,
            callback=self._on_changed,
        )[0].result(timeout=30)
        self.jobs.subscribe_to_start_next_pending_job_execution_accepted(
            j.StartNextPendingJobExecutionSubscriptionRequest(thing_name=self.thing),
            qos=self.qos,
            callback=self._on_started,
        )[0].result(timeout=30)
        self._ask_next()

    def _ask_next(self) -> None:
        self.jobs.publish_start_next_pending_job_execution(
            self.iotjobs.StartNextPendingJobExecutionRequest(thing_name=self.thing), qos=self.qos
        )

    def _on_changed(self, event) -> None:
        if getattr(event, "execution", None) and not self._busy.locked():
            self._ask_next()

    def _on_started(self, response) -> None:
        ex = getattr(response, "execution", None)
        if ex is None or ex.job_id is None:
            return
        import threading

        threading.Thread(target=self._run, args=(ex,), daemon=True).start()

    def _report(
        self, job_id: str, status, details: dict[str, str], version: int | None = None
    ) -> None:
        req = self.iotjobs.UpdateJobExecutionRequest(
            thing_name=self.thing,
            job_id=job_id,
            status=status,
            status_details=details,
        )
        self.jobs.publish_update_job_execution(req, qos=self.qos)

    def _run(self, ex) -> None:
        with self._busy:
            job_id, doc = ex.job_id, ex.job_document or {}
            JS = self.iotjobs.JobStatus
            log.info("job %s: %s", job_id, doc)
            self._report(job_id, JS.IN_PROGRESS, {"step": "starting", "op": str(doc.get("op"))})
            op = str(doc.get("op"))
            result = self.executor.run(
                doc,
                progress=lambda step: self._report(
                    job_id, JS.IN_PROGRESS, {"step": step, "op": op}
                ),
            )
            status = JS.SUCCEEDED if result.ok else (JS.REJECTED if result.rejected else JS.FAILED)
            details = {k: str(v)[:1000] for k, v in result.details.items()}
            self._report(job_id, status, details)
            self.last = {"job": job_id, "op": doc.get("op"), "status": str(status), **details}
            log.info("job %s -> %s %s", job_id, status, details.get("reason", ""))
        self._ask_next()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stdout)
    thing = os.environ["HACKLAB_THING"]
    iot_dir = Path(os.environ.get("HACKLAB_IOT_DIR", "/opt/hacklab/data/iot"))
    client = MqttClient(
        endpoint=os.environ["HACKLAB_IOT_ENDPOINT"],
        iot_dir=iot_dir,
        client_id=thing or socket.gethostname(),
    )
    log.info("connected as %s", thing)
    worker = None
    if os.environ.get("HACKLAB_BUCKET") and os.environ.get("HACKLAB_CRED_ENDPOINT"):
        from awsio import S3, IotCredentials, minisign_verify, sudo_apply
        from jobs import JobExecutor

        alias = os.environ.get("HACKLAB_ROLE_ALIAS", "hacklab-device")
        creds = IotCredentials(os.environ["HACKLAB_CRED_ENDPOINT"], thing, alias, iot_dir)
        executor = JobExecutor(
            thing=thing,
            releases_dir=Path("/opt/hacklab/releases"),
            logs_dir=Path(os.environ.get("HACKLAB_DATA_DIR", "/opt/hacklab/data")),
            pubkey=Path("/opt/hacklab/minisign.pub"),
            s3=S3(
                os.environ["HACKLAB_BUCKET"],
                os.environ.get("HACKLAB_AWS_REGION", "eu-west-1"),
                creds,
            ),
            apply=sudo_apply,
            verify=minisign_verify,
        )
        worker = JobsWorker(client.conn, thing, executor)
        worker.start()
        log.info("jobs: listening (bucket %s)", os.environ["HACKLAB_BUCKET"])
    else:
        log.info("jobs: disabled (HACKLAB_BUCKET / HACKLAB_CRED_ENDPOINT not set)")
    hb = Heartbeat(
        client,
        thing,
        collect=lambda: {**collect_state(), "last_job": worker.last if worker else None},
    )
    hb.run(float(os.environ.get("HACKLAB_OPS_INTERVAL", "300")))


if __name__ == "__main__":
    main()
