"""Tweakable values via the Hack Pack IDE's trailing-comment markers.

A line such as `int yawMoveSpeed = 90; // speed -- ///{"range":[10,90],"step":10}`
or `upMove(1); ///{"range":[1,10]}` declares one tweakable: the last numeric or
boolean literal in the code part of the line. Marker forms: `range` [lo, hi],
`min`/`max`, `step`, `options` [..], optional `name`. Rendering replaces that
literal only, clamped to the range and snapped to the step.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

MARKER = re.compile(r"///\s*(\{.*\})\s*$")
LITERAL = re.compile(r"\b(true|false)\b|-?\d+(?:\.\d+)?")
DECL = re.compile(r"\b([A-Za-z_]\w*)\s*=\s*$")
CALL = re.compile(r"\b([A-Za-z_]\w*)\s*\(\s*$")


class TemplateError(ValueError):
    pass


@dataclass
class Tweakable:
    name: str
    value: int | float | bool
    line: int  # 1-based
    span: tuple[int, int]  # literal position within the line
    range: tuple[float, float] | None = None
    step: float | None = None
    options: list[str] | None = None
    label: str | None = None  # our extension: kid-facing slider label

    def to_api(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name, "value": self.value}
        if self.label:
            d["label"] = self.label
        if self.range:
            d["range"] = [_num(self.range[0]), _num(self.range[1])]
        if self.step is not None:
            d["step"] = _num(self.step)
        if self.options is not None:
            d["options"] = self.options
        return d


def _num(x: float) -> int | float:
    return int(x) if float(x).is_integer() else x


def _parse_literal(text: str) -> int | float | bool:
    if text in ("true", "false"):
        return text == "true"
    return float(text) if "." in text else int(text)


def find_tweakables(source: str) -> list[Tweakable]:
    out: list[Tweakable] = []
    seen: dict[str, int] = {}
    for n, line in enumerate(source.splitlines(), 1):
        m = MARKER.search(line)
        if not m:
            continue
        try:
            marker = json.loads(m.group(1))
        except json.JSONDecodeError as exc:
            raise TemplateError(f"bad marker on line {n}: {exc.msg}") from exc
        code = line[: m.start()].split("//")[
            0
        ]  # ponytail: '//' inside a string literal would confuse this
        lits = list(LITERAL.finditer(code))
        if not lits:
            raise TemplateError(f"marker on line {n} has no literal to tweak")
        lit = lits[-1]
        before = code[: lit.start()]
        name = marker.get("name") or _guess_name(before, n)
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 1
        rng = None
        if "range" in marker:
            rng = (float(marker["range"][0]), float(marker["range"][1]))
        elif "min" in marker or "max" in marker:
            rng = (float(marker.get("min", float("-inf"))), float(marker.get("max", float("inf"))))
        out.append(
            Tweakable(
                name=name,
                value=_parse_literal(lit.group(0)),
                line=n,
                span=(lit.start(), lit.end()),
                range=rng,
                step=float(marker["step"]) if "step" in marker else None,
                options=[str(o) for o in marker["options"]] if "options" in marker else None,
                label=marker.get("label"),
            )
        )
    return out


def _guess_name(before: str, n: int) -> str:
    m = DECL.search(before) or CALL.search(before)
    return m.group(1) if m else f"tweak_{n}"


def render(source: str, values: dict[str, Any]) -> str:
    """Return `source` with the named tweakables replaced; unknown names and
    off-list options raise TemplateError, numbers are clamped and snapped."""
    tws = {t.name: t for t in find_tweakables(source)}
    unknown = set(values) - set(tws)
    if unknown:
        raise TemplateError(f"unknown tweakable(s): {', '.join(sorted(unknown))}")
    lines = source.split("\n")
    for name, raw in values.items():
        t = tws[name]
        new = _format(t, raw)
        line = lines[t.line - 1]
        lines[t.line - 1] = line[: t.span[0]] + new + line[t.span[1] :]
    return "\n".join(lines)


def _format(t: Tweakable, raw: Any) -> str:
    if t.options is not None or isinstance(t.value, bool):
        text = str(raw).lower() if isinstance(raw, bool) else str(raw)
        allowed = t.options if t.options is not None else ["true", "false"]
        if text not in allowed:
            raise TemplateError(f"{t.name}: {raw!r} is not one of {allowed}")
        return text
    try:
        v = float(raw)
    except (TypeError, ValueError) as exc:
        raise TemplateError(f"{t.name}: {raw!r} is not a number") from exc
    if t.range:
        lo, hi = t.range
        v = min(max(v, lo), hi)
        if t.step:
            v = lo + round((v - lo) / t.step) * t.step
            v = min(v, hi)
    elif t.step:
        v = round(v / t.step) * t.step
    if isinstance(t.value, int) and (t.step is None or float(t.step).is_integer()):
        return str(int(round(v)))
    return repr(_num(round(v, 6)))
