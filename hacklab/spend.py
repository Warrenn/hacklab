"""Monthly spend ledger for the AI helper: one JSONL line per API call,
cost from a small price table, hard cap checked before every ask."""

from __future__ import annotations

import json
import time
from pathlib import Path

# USD per million tokens: input, output, cache read, cache write (5 min)
PRICES = {
    "claude-sonnet-5-5": (2.00, 10.00, 0.20, 2.50),
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
}


def _month(ts: float | None = None) -> str:
    return time.strftime("%Y-%m", time.gmtime(ts))


class SpendLedger:
    def __init__(self, data_dir: Path | str):
        self.dir = Path(data_dir) / "spend"

    def record(self, model: str, usage, month: str | None = None) -> float:
        pi, po, pr, pw = PRICES.get(model, (0.0, 0.0, 0.0, 0.0))
        tokens = {
            "input": getattr(usage, "input_tokens", 0) or 0,
            "output": getattr(usage, "output_tokens", 0) or 0,
            "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
            "cache_write": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        }
        cost = (
            tokens["input"] * pi
            + tokens["output"] * po
            + tokens["cache_read"] * pr
            + tokens["cache_write"] * pw
        ) / 1e6
        cost = round(cost, 6)
        self.dir.mkdir(parents=True, exist_ok=True)
        with (self.dir / f"{month or _month()}.jsonl").open("a") as f:
            f.write(
                json.dumps({"ts": int(time.time()), "model": model, **tokens, "usd": cost}) + "\n"
            )
        return cost

    def month_total(self, month: str | None = None) -> float:
        f = self.dir / f"{month or _month()}.jsonl"
        if not f.is_file():
            return 0.0
        return round(
            sum(json.loads(ln)["usd"] for ln in f.read_text().splitlines() if ln.strip()), 6
        )

    def over_cap(self, cap_usd: float, month: str | None = None) -> bool:
        return self.month_total(month) >= cap_usd
