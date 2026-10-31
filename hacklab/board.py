"""Board backends: `ArduinoCli` (real, subprocess) and `FakeBoard` (scripted).

Both expose list_ports / compile / upload so the Flasher never knows which it
has. JSON shapes were recorded from arduino-cli 1.5.1 on the Pi (STRATEGY.md
P1 plan).
"""

from __future__ import annotations

import glob
import json
import re
import subprocess
import threading
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

# USB-serial chips used by Nano clones. arduino-cli reports no matching board
# for these, so detection is by VID:PID (lower-case hex strings).
KNOWN_NANO = {
    ("0x1a86", "0x7523"),  # CH340 (Hack Pack boards seen so far)
    ("0x1a86", "0x55d4"),  # CH9102
    ("0x0403", "0x6001"),  # FTDI FT232R
    ("0x10c4", "0xea60"),  # CP2102
    ("0x2341", "0x0043"),  # Arduino Uno/Nano official
}


@dataclass(frozen=True)
class Port:
    address: str
    vid: str
    pid: str
    serial: str


@dataclass
class Result:
    ok: bool
    log: str
    sizes: dict[str, tuple[int, int]] = field(default_factory=dict)


class CliError(RuntimeError):
    pass


class Board(Protocol):
    def list_ports(self) -> list[Port]: ...
    def device_nodes(self) -> frozenset[str]: ...  # cheap: which serial devices exist right now
    def compile(self, sketch_dir: Path, fqbn: str, out_dir: Path) -> Result: ...
    def upload(self, sketch_dir: Path, fqbn: str, port: str, build_dir: Path) -> Result: ...


REGISTRY = Path(__file__).resolve().parent.parent / "provisioning" / "boards.toml"
_USB_ID = re.compile(r"^[0-9a-fA-F]{4}:[0-9a-fA-F]{4}$")


@dataclass(frozen=True)
class BoardSpec:
    """One entry of provisioning/boards.toml (P6): how a board family is
    detected, which fqbn variants to try, and how it behaves after an upload."""

    fqbn: str
    core: str
    cpu_options: tuple[str, ...]
    usb_ids: frozenset[tuple[str, str]]  # ("0x1a86", "0x7523") like Port.vid/pid
    reenumerates: bool
    upload_timeout: float
    verified: bool

    def fqbns(self) -> list[str]:
        """Upload candidates in order: one per cpu option, or the bare fqbn."""
        return [f"{self.fqbn}:cpu={c}" for c in self.cpu_options] or [self.fqbn]


class Registry(dict):
    additional_urls: list[str] = []


def load_registry(path: Path | str = REGISTRY) -> Registry:
    doc = tomllib.loads(Path(path).read_text())
    reg = Registry()
    reg.additional_urls = list(doc.get("cores", {}).get("additional_urls", []))
    for fqbn, b in doc.get("boards", {}).items():
        if not b.get("core"):
            raise ValueError(f"boards.toml {fqbn}: missing core")
        ids = b.get("usb_ids", [])
        bad = [i for i in ids if not _USB_ID.match(str(i))]
        if bad:
            raise ValueError(f"boards.toml {fqbn}: usb_ids must be vvvv:pppp hex, got {bad}")
        reg[fqbn] = BoardSpec(
            fqbn=fqbn,
            core=b["core"],
            cpu_options=tuple(b.get("cpu_options", [])),
            usb_ids=frozenset(
                ("0x" + i.split(":")[0].lower(), "0x" + i.split(":")[1].lower()) for i in ids
            ),
            reenumerates=bool(b.get("reenumerates", False)),
            upload_timeout=float(b.get("upload_timeout", 240)),
            verified=bool(b.get("verified", False)),
        )
    return reg


def board_spec(fqbn: str, path: Path | str = REGISTRY) -> BoardSpec:
    reg = load_registry(path)
    if fqbn not in reg:
        raise KeyError(f"{fqbn!r} is not in provisioning/boards.toml (known: {', '.join(reg)})")
    return reg[fqbn]


def find_board(ports: list[Port], spec: BoardSpec | None = None) -> Port | None:
    ids = spec.usb_ids if spec else KNOWN_NANO
    return next((p for p in ports if (p.vid, p.pid) in ids), None)


Runner = Callable[[list[str], float], tuple[int, str, str]]


def run_subprocess(argv: list[str], timeout: float) -> tuple[int, str, str]:
    p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


class ArduinoCli:
    def __init__(
        self, cli: str, config: str | None, run: Runner = run_subprocess, timeout: float = 240
    ):
        self.base = [cli] + (["--config-file", config] if config else [])
        self.run, self.timeout = run, timeout

    def _json(self, args: list[str]) -> tuple[int, dict, str]:
        rc, out, err = self.run(self.base + ["--json"] + args, self.timeout)
        try:
            data = json.loads(out) if out.strip() else {}
        except json.JSONDecodeError as exc:
            if rc != 0:  # avrdude failures are plain text
                return rc, {}, out + err
            raise CliError(f"arduino-cli returned non-JSON: {out[:200]}") from exc
        return rc, data, err

    # ponytail: a 1 s glob of the device nodes instead of udev; `board list` costs seconds on a Pi 3
    device_globs: tuple[str, ...] = ("/dev/ttyUSB*", "/dev/ttyACM*", "/dev/cu.usb*")

    def device_nodes(self) -> frozenset[str]:
        return frozenset(n for pat in self.device_globs for n in glob.glob(pat))

    # Linux: read the ports from the kernel (instant). `board list` waits out its
    # discovery timeout and took 12.7 s on the Pi 3, which was the plug/unplug lag.
    sysfs_tty = Path("/sys/class/tty")

    def list_ports(self) -> list[Port]:
        if self.sysfs_tty.is_dir():
            return self._sysfs_ports()
        # macOS dev box: no sysfs, fall back to arduino-cli's discovery (slow but complete)
        _, data, _ = self._json(["board", "list", "--discovery-timeout", "5s"])
        ports = []
        for item in data.get("detected_ports", []):
            p, props = item.get("port", {}), item.get("port", {}).get("properties")
            if p.get("protocol") == "serial" and props:
                ports.append(
                    Port(
                        p["address"],
                        props.get("vid", "").lower(),
                        props.get("pid", "").lower(),
                        props.get("serialNumber", ""),
                    )
                )
        return ports

    def _sysfs_ports(self) -> list[Port]:
        ports = []
        for tty in sorted(p for pat in ("ttyUSB*", "ttyACM*") for p in self.sysfs_tty.glob(pat)):
            dev = (tty / "device").resolve()
            usb = next((d for d in (dev, *dev.parents) if (d / "idVendor").is_file()), None)
            if usb is None:
                continue  # not a USB serial adapter (e.g. the Pi's own UART)

            def attr(name: str, usb: Path = usb) -> str:
                f = usb / name
                return f.read_text().strip() if f.is_file() else ""

            ports.append(
                Port(
                    f"/dev/{tty.name}",
                    "0x" + attr("idVendor").lower(),
                    "0x" + attr("idProduct").lower(),
                    attr("serial"),
                )
            )
        return ports

    def compile(self, sketch_dir: Path, fqbn: str, out_dir: Path) -> Result:
        rc, d, err = self._json(
            ["compile", "--fqbn", fqbn, "--output-dir", str(out_dir), str(sketch_dir)]
        )
        sizes = {
            s["name"]: (s["size"], s["max_size"])
            for s in d.get("builder_result", {}).get("executable_sections_size", [])
        }
        parts = (d.get("compiler_out", ""), d.get("compiler_err", ""), d.get("error", ""), err)
        log = "\n".join(x for x in parts if x)
        return Result(ok=rc == 0 and bool(d.get("success")), log=log, sizes=sizes)

    def upload(self, sketch_dir: Path, fqbn: str, port: str, build_dir: Path) -> Result:
        rc, d, err = self._json(
            [
                "upload",
                "--fqbn",
                fqbn,
                "--port",
                port,
                "--input-dir",
                str(build_dir),
                "--verify",
                str(sketch_dir),
            ]
        )
        log = "\n".join(
            x for x in (d.get("stdout", ""), d.get("stderr", ""), d.get("error", ""), err) if x
        )
        return Result(ok=rc == 0, log=log)


class FakeBoard:
    """Emulated Nano. Set attributes to script failures; counters for assertions."""

    def __init__(self):
        self.unplugged = False
        self.compile_error: str | None = None
        self.upload_fails_for: set[str] = set()  # cpu values that fail, e.g. {"atmega328"}
        self.vanish_after_upload = False
        self.reenumerate_gap = 0  # listings the port stays gone after an upload (native-USB boards)
        self.port = Port("/dev/ttyFAKE0", "0x1a86", "0x7523", "")  # a CH340 Nano clone by default
        self.compiles = self.uploads = 0
        self.last_uploaded_source: str | None = None
        self.last_sketch_files: list[str] = []
        self.last_fqbn: str | None = None
        self.max_concurrent = 0
        self._active = 0
        self._gap = 0
        self._lock = threading.Lock()

    def list_ports(self) -> list[Port]:
        if self._gap > 0:
            self._gap -= 1
            return []
        return [] if self.unplugged else [self.port]

    def device_nodes(self) -> frozenset[str]:
        return frozenset() if self.unplugged else frozenset({self.port.address})

    def compile(self, sketch_dir: Path, fqbn: str, out_dir: Path) -> Result:
        self.compiles += 1
        if self.compile_error:
            return Result(False, self.compile_error)
        self.last_sketch_files = sorted(p.name for p in Path(sketch_dir).iterdir())
        main = Path(sketch_dir) / f"{Path(sketch_dir).name}.ino"
        if not main.is_file():  # arduino-cli rule, seen on the Pi
            return Result(False, f"Can't open sketch: main file missing from sketch: {main}")
        out_dir.mkdir(parents=True, exist_ok=True)
        ino = sorted(Path(sketch_dir).glob("*.ino"))
        (out_dir / "sketch.ino.hex").write_text(ino[0].read_text() if ino else "")
        return Result(True, "Sketch uses 1868 bytes", {"text": (1868, 30720), "data": (328, 2048)})

    def upload(self, sketch_dir: Path, fqbn: str, port: str, build_dir: Path) -> Result:
        with self._lock:
            self._active += 1
            self.max_concurrent = max(self.max_concurrent, self._active)
        try:
            self.uploads += 1
            self.last_fqbn = fqbn
            cpu = fqbn.rsplit("cpu=", 1)[-1] if "cpu=" in fqbn else ""
            if cpu in self.upload_fails_for:
                return Result(False, "avrdude: stk500_recv(): programmer is not responding")
            hexfile = Path(build_dir) / "sketch.ino.hex"
            self.last_uploaded_source = hexfile.read_text() if hexfile.exists() else None
            if self.vanish_after_upload:
                self.unplugged = True
            self._gap = self.reenumerate_gap
            return Result(True, "avrdude done.  Thank you.")
        finally:
            with self._lock:
                self._active -= 1
