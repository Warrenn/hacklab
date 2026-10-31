"""Configuration: config.toml (optional) + environment overrides.

The Anthropic API key is read from the environment only; a value in the file
is ignored so a copied config.toml can never leak it.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

_TRUTHY = {"1", "true", "yes", "on"}


@dataclass
class Config:
    host: str = "0.0.0.0"
    port: int = 8000
    data_dir: Path = field(default_factory=lambda: Path("data"))
    fake_board: bool = False
    watch_interval: float = 1.0  # seconds between serial device checks (plug/unplug push)
    allowed_hosts: list[str] = field(default_factory=list)  # extra Host names besides the built-ins
    model: str = "claude-sonnet-5-5"
    api_key: str | None = None
    arduino_cli: str = "/opt/hacklab/bin/arduino-cli"
    arduino_config: str | None = "/opt/hacklab/arduino/arduino-cli.yaml"
    boxes_dir: Path = field(
        default_factory=lambda: Path(__file__).resolve().parent.parent / "boxes"
    )
    board: str = (
        "arduino-cli"  # "fake" = real runner + store + genie on FakeBoard (dev without hardware)
    )


def load_config(path: Path | str = "config.toml", env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env
    # the appliance points HACKLAB_CONFIG at /etc/hacklab/config.toml
    path = Path(env.get("HACKLAB_CONFIG") or path)
    raw = tomllib.loads(path.read_text()) if path.is_file() else {}
    app, ai = raw.get("app", {}), raw.get("ai", {})
    cfg = Config(
        host=app.get("host", Config.host),
        port=int(app.get("port", Config.port)),
        data_dir=Path(app.get("data_dir", "data")),
        fake_board=bool(app.get("fake_board", False)),
        model=ai.get("model", Config.model),
        arduino_cli=app.get("arduino_cli", Config.arduino_cli),
        arduino_config=app.get("arduino_config", Config.arduino_config),
        allowed_hosts=[str(h).lower() for h in app.get("allowed_hosts", [])],
    )
    if app.get("boxes_dir"):
        cfg.boxes_dir = Path(app["boxes_dir"])
    if env.get("HACKLAB_BOXES_DIR"):
        cfg.boxes_dir = Path(env["HACKLAB_BOXES_DIR"])
    cfg.board = env.get("HACKLAB_BOARD") or app.get("board", Config.board)
    if "FAKE_BOARD" in env:
        cfg.fake_board = env["FAKE_BOARD"].strip().lower() in _TRUTHY
    if env.get("HACKLAB_DATA_DIR"):
        cfg.data_dir = Path(env["HACKLAB_DATA_DIR"])
    cfg.api_key = env.get("ANTHROPIC_API_KEY") or None
    return cfg
