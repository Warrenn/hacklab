"""Flasher: detect -> compile -> upload (bootloader fallback, cached per box) -> verify."""

from __future__ import annotations

import json
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from hacklab.board import Board, Port, find_board

FQBN = "arduino:avr:nano:cpu={cpu}"
CPUS = ["atmega328", "atmega328old"]  # new bootloader first; order rotates per cached box
DETECT_TTL = 10.0  # seconds a detect() result is reused by /api/status

KID = {
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
    ):
        self.board, self.data_dir = board, Path(data_dir)
        self.timeout, self.sleep = reenumerate_timeout, sleep
        self.clock, self.detect_ttl = clock, DETECT_TTL if detect_ttl is None else detect_ttl
        self._cached: tuple[float, Port | None] | None = None
        self._refreshing = threading.Lock()

    def detect(self, fresh: bool = False) -> Port | None:
        """The attached box. `arduino-cli board list` costs ~10 s on a Pi 3 and
        /api/status polls this, so a cached answer is returned at once and, when
        stale, refreshed in a background thread; the first call blocks."""
        if not fresh and self._cached:
            if self.clock() - self._cached[0] >= self.detect_ttl and not self._refreshing.locked():
                threading.Thread(target=self._refresh, daemon=True).start()
            return self._cached[1]
        return self._refresh()

    def _refresh(self) -> Port | None:
        if not self._refreshing.acquire(blocking=False):
            return self._cached[1] if self._cached else None
        try:
            return self._probe()
        finally:
            self._refreshing.release()

    def _probe(self) -> Port | None:
        self.last_ports: list[Port] = []
        self.last_error: str | None = None
        try:
            self.last_ports = self.board.list_ports()
            port = find_board(self.last_ports)
        except Exception as exc:  # noqa: BLE001 - a flaky CLI call means "not connected", not a crash
            self.last_error = f"{type(exc).__name__}: {exc}"
            port = None
        self._cached = (self.clock(), port)
        return port

    def flash(self, box: str, sketch_dir: Path, progress: Callable[[str], None]) -> FlashResult:
        log: list[str] = []
        port = self.detect(fresh=True)
        if port is None:
            log.append(f"[detect] ports={self.last_ports} error={self.last_error}")
            return self._fail("detecting", log)
        progress("compiling")
        build = Path(tempfile.mkdtemp(prefix="hacklab-build-"))
        c = self.board.compile(sketch_dir, FQBN.format(cpu=self._cpus(box)[0]), build)
        log.append(c.log)
        if c.sizes:
            log.append(" ".join(f"{k}={s}/{m}" for k, (s, m) in c.sizes.items()))
        if not c.ok:
            return self._fail("compiling", log)
        progress("uploading")
        cpu_used = None
        for cpu in self._cpus(box):
            u = self.board.upload(sketch_dir, FQBN.format(cpu=cpu), port.address, build)
            log.append(f"[upload cpu={cpu}] {u.log}")
            if u.ok:
                cpu_used = cpu
                break
        if cpu_used is None:
            return self._fail("uploading", log)
        self._remember(box, cpu_used)
        progress("verifying")
        if not self._still_there(port):
            return self._fail("verifying", log, cpu=cpu_used, port=port.address)
        return FlashResult(True, "\n".join(log), cpu=cpu_used, port=port.address)

    # -- helpers -----------------------------------------------------------
    def _fail(self, stage: str, log: list[str], **kw) -> FlashResult:
        return FlashResult(False, "\n".join(log), failed_stage=stage, message_kid=KID[stage], **kw)

    def _still_there(self, port: Port) -> bool:
        deadline = time.monotonic() + self.timeout
        while True:
            self.detect(fresh=True)  # one CLI call (~10 s on a Pi 3); ports land in last_ports
            same = [
                p
                for p in self.last_ports
                if (port.serial and p.serial == port.serial) or p.address == port.address
            ]
            if same:
                return True
            if time.monotonic() >= deadline:
                return False
            self.sleep(0.25)

    def _cache(self, box: str) -> Path:
        return self.data_dir / box / "board.json"

    def _cpus(self, box: str) -> list[str]:
        f = self._cache(box)
        if f.is_file():
            cached = json.loads(f.read_text()).get("cpu")
            if cached in CPUS:
                return [cached] + [c for c in CPUS if c != cached]
        return list(CPUS)

    def _remember(self, box: str, cpu: str) -> None:
        f = self._cache(box)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"cpu": cpu}))
