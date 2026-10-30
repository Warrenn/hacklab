"""Spend ledger: per-call cost, monthly total, cap."""

from pathlib import Path
from types import SimpleNamespace

from hacklab.spend import SpendLedger


def usage(i=1000, o=500, cr=0, cw=0):
    return SimpleNamespace(
        input_tokens=i, output_tokens=o, cache_read_input_tokens=cr, cache_creation_input_tokens=cw
    )


def test_cost_uses_the_model_price_table(tmp_path: Path):
    led = SpendLedger(tmp_path / "data")
    cost = led.record("claude-sonnet-5-5", usage(1_000_000, 100_000), month="2026-10")
    assert cost == 2.0 + 1.0
    assert (
        led.record("claude-sonnet-5-5", usage(0, 0, cr=1_000_000, cw=1_000_000), month="2026-10")
        == 0.20 + 2.50
    )


def test_totals_persist_and_cap(tmp_path: Path):
    led = SpendLedger(tmp_path / "data")
    led.record("claude-sonnet-5-5", usage(), month="2026-10")
    led.record("claude-sonnet-5-5", usage(), month="2026-10")
    led.record("claude-sonnet-5-5", usage(), month="2026-11")
    again = SpendLedger(tmp_path / "data")
    assert again.month_total("2026-10") == round(2 * (0.002 + 0.005), 6)
    assert again.month_total("2026-11") == round(0.007, 6)
    assert again.over_cap(0.01, month="2026-10") is True
    assert again.over_cap(10, month="2026-10") is False
    assert again.month_total("2025-01") == 0.0


def test_unknown_model_costs_zero_but_is_recorded(tmp_path: Path):
    led = SpendLedger(tmp_path / "data")
    assert led.record("claude-mystery", usage(), month="2026-10") == 0.0
    assert (tmp_path / "data" / "spend" / "2026-10.jsonl").read_text().count("\n") == 1
