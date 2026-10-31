"""Flasher: detect -> compile -> upload (bootloader fallback, cached per box) -> verify.

Which board to look for, which fqbn variants to try and whether the port
re-enumerates after an upload come from the box's BoardSpec
(provisioning/boards.toml, P6); the Nano spec is the default.
"""

from __future__ import annotations

import json
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from hacklab.board import Board, BoardSpec, Port, board_spec, find_board

NANO_FQBN = "arduino:avr:nano"
DETECT_TTL = 10.0  # seconds a detect() result is reused by /api/status

KID = {
    "stopped": "Stopped. Nothing was changed.",
    "detecting": "I can't find the box. Is the USB cable plugged in?",
    "compiling": "That code did not build. Try again, or press Undo.",
    "uploading": "The box did not take the code. Check the cable and try again.",
    "verifying": "The box did not wake up. Try again, or press Back to how it came.",
}


@dataclass
class FlashResult:
    ok: bool
    log: str
    failed_stage: str | None = None
    message_kid: str = ""
    cpu: str | None = None
    port: str | None = None


class Flasher:
    def __init__(
        self,
        board: Board,
        data_dir: Path,
        reenumerate_timeout: float = 10.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        detect_ttl: float | None = None,
        spec: BoardSpec | None = None,
    ):
        self.board, self.data_dir = board, Path(data_dir)
        self.timeout, self.sleep = reenumerate_timeout, sleep
        self.clock, self.detect_ttl = clock, DETECT_TTL if detect_ttl is None else detect_ttl
        self.spec = spec or board_spec(NANO_FQBN)  # what detect() looks for when no spec is given
        self._cached: tuple[float, Port | None] | None = None
        self._refreshing = threading.Lock()

    def detect(self, fresh: bool = False, spec: BoardSpec | None = None) -> Port | None:
        """The attached box. `arduino-cli board list` costs ~10 s on a Pi 3 and
        /api/status polls this, so a cached answer is returned at once and, when
        stale, refreshed in a background thread; the first call blocks."""
        spec = spec or self.spec
        if not fresh and self._cached:
            if self.clock() - self._cached[0] >= self.detect_ttl and not self._refreshing.locked():
                threading.Thread(target=self._refresh, args=(spec,), daemon=True).start()
            return self._cached[1]
        return self._refresh(spec)

    def _refresh(self, spec: BoardSpec) -> Port | None:
        if not self._refreshing.acquire(blocking=False):
            return self._cached[1] if self._cached else None
        try:
            return self._probe(spec)
        finally:
            self._refreshing.release()

    def _probe(self, spec: BoardSpec) -> Port | None:
        self.last_ports: list[Port] = []
        self.last_error: str | None = None
        try:
            self.last_ports = self.board.list_ports()
            port = find_board(self.last_ports, spec)
        except Exception as exc:  # noqa: BLE001 - a flaky CLI call means "not connected", not a crash
            self.last_error = f"{type(exc).__name__}: {exc}"
            port = None
        self._cached = (self.clock(), port)
        return port

    def flash(
        self,
        box: str,
        sketch_dir: Path,
        progress: Callable[[str], None],
        spec: BoardSpec | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> FlashResult:
        """Compile, upload, verify. `should_stop` is asked before the compile and before the
        upload (never during: a half-written board is worse than a finished flash)."""
        spec = spec or self.spec
        log: list[str] = []
        if should_stop and should_stop():
            return self._fail("stopped", log)
        port = self.detect(fresh=True, spec=spec)
        if port is None:
            log.append(f"[detect] ports={self.last_ports} error={self.last_error}")
            return self._fail("detecting", log)
        candidates = self._candidates(box, spec)
        progress("compiling")
        build = Path(tempfile.mkdtemp(prefix="hacklab-build-"))
        c = self.board.compile(sketch_dir, candidates[0], build)
        log.append(c.log)
        if c.sizes:
            log.append(" ".join(f"{k}={s}/{m}" for k, (s, m) in c.sizes.items()))
        if not c.ok:
            return self._fail("compiling", log)
        if should_stop and should_stop():
            return self._fail("stopped", log)
        progress("uploading")
        fqbn_used = None
        for fqbn in candidates:
            u = self.board.upload(sketch_dir, fqbn, port.address, build)
            log.append(f"[upload {fqbn}] {u.log}")
            if u.ok:
                fqbn_used = fqbn
                break
        if fqbn_used is None:
            return self._fail("uploading", log)
        cpu = fqbn_used.rsplit("cpu=", 1)[-1] if "cpu=" in fqbn_used else None
        if cpu:
            self._remember(box, cpu)
        progress("verifying")
        if not self._came_back(port, spec):
            return self._fail("verifying", log, cpu=cpu, port=port.address)
        return FlashResult(True, "\n".join(log), cpu=cpu, port=port.address)

    # -- helpers -----------------------------------------------------------
    def _fail(self, stage: str, log: list[str], **kw) -> FlashResult:
        return FlashResult(False, "\n".join(log), failed_stage=stage, message_kid=KID[stage], **kw)

    def _same(self, port: Port, spec: BoardSpec) -> list[Port]:
        return [
            p
            for p in self.last_ports
            if (port.serial and p.serial == port.serial)
            or (p.address == port.address)
            or (spec.reenumerates and (p.vid, p.pid) in spec.usb_ids)
        ]

    def _came_back(self, port: Port, spec: BoardSpec) -> bool:
        """Non-reenumerating boards: the port must still be listed. Re-enumerating
        boards: the port may drop off the bus during the reset; wait for it (same
        serial when there is one, else any port of that board family) to return."""
        deadline = time.monotonic() + self.timeout
        while True:
            self.detect(
                fresh=True, spec=spec
            )  # one CLI call (~10 s on a Pi 3); ports in last_ports
            if self._same(port, spec):
                return True
            if time.monotonic() >= deadline:
                return False
            self.sleep(0.25)

    def _cache(self, box: str) -> Path:
        return self.data_dir / box / "board.json"

    def _candidates(self, box: str, spec: BoardSpec) -> list[str]:
        """fqbn variants in the order to try; the cpu option that worked last
        time for this box goes first."""
        fqbns = spec.fqbns()
        f = self._cache(box)
        if f.is_file() and spec.cpu_options:
            cached = json.loads(f.read_text()).get("cpu")
            if cached in spec.cpu_options:
                first = f"{spec.fqbn}:cpu={cached}"
                return [first] + [x for x in fqbns if x != first]
        return fqbns

    def _remember(self, box: str, cpu: str) -> None:
        f = self._cache(box)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"cpu": cpu}))
