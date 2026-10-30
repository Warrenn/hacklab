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
    model: str = "claude-sonnet-5-5"
    monthly_cap_usd: float = 10
    api_key: str | None = None
    arduino_cli: str = "/opt/hacklab/bin/arduino-cli"
    arduino_config: str | None = "/opt/hacklab/arduino/arduino-cli.yaml"


def load_config(path: Path | str = "config.toml", env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env
    path = Path(path)
    raw = tomllib.loads(path.read_text()) if path.is_file() else {}
    app, ai = raw.get("app", {}), raw.get("ai", {})
    cfg = Config(
        host=app.get("host", Config.host),
        port=int(app.get("port", Config.port)),
        data_dir=Path(app.get("data_dir", "data")),
        fake_board=bool(app.get("fake_board", False)),
        model=ai.get("model", Config.model),
        monthly_cap_usd=float(ai.get("monthly_cap_usd", Config.monthly_cap_usd)),
        arduino_cli=app.get("arduino_cli", Config.arduino_cli),
        arduino_config=app.get("arduino_config", Config.arduino_config),
    )
    if "FAKE_BOARD" in env:
        cfg.fake_board = env["FAKE_BOARD"].strip().lower() in _TRUTHY
    if env.get("HACKLAB_DATA_DIR"):
        cfg.data_dir = Path(env["HACKLAB_DATA_DIR"])
    cfg.api_key = env.get("ANTHROPIC_API_KEY") or None
    return cfg
