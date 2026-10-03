"""Number formatting used in check messages; ports of the prototype's helpers."""

import math
import re


def _round_half_up(x: float) -> int:
    return math.floor(x + 0.5)


def _strip(s: str) -> str:
    # JS: s.replace(/\.0+$/,'').replace(/(\.\d*[1-9])0+$/,'$1')
    s = re.sub(r"\.0+$", "", s)
    return re.sub(r"(\.\d*[1-9])0+$", r"\1", s)


def trim(x: float) -> str:
    s = f"{x:.0f}" if x >= 100 else f"{x:.1f}" if x >= 10 else f"{x:.2f}"
    return _strip(s)


def money(v: float | None) -> str:
    if v is None or not math.isfinite(v):
        return "—"
    a = abs(v)
    if a >= 1e9:
        return f"${trim(v / 1e9)}B"
    if a >= 1e6:
        return f"${trim(v / 1e6)}M"
    if a >= 1e3:
        return f"${trim(v / 1e3)}K"
    return f"${_round_half_up(v)}"


def pct(p: float | None) -> str:
    if p is None or not math.isfinite(p):
        return "—"
    if 0 < p < 0.001:
        return "<0.1%"
    x = p * 100
    s = re.sub(r"\.0$", "", f"{x:.1f}") if x < 10 else f"{x:.0f}"
    return s + "%"


def freq(f: float) -> str:
    if not math.isfinite(f):
        return "—"
    if f >= 10:
        return f"{f:.0f}"
    if f >= 1:
        return re.sub(r"\.0$", "", f"{f:.1f}")
    if f >= 0.1:
        return f"{f:.2f}"
    # JS toPrecision(2)
    if f == 0:
        return "0.0"
    digits = 2 - 1 - math.floor(math.log10(abs(f)))
    return f"{f:.{max(digits, 0)}f}"


def every(f: float) -> str:
    if not (f > 0):
        return "never in the simulation"
    if f >= 1:
        return f"about {freq(f)} times a year"
    y = 1 / f
    s = re.sub(r"\.0$", "", f"{y:.1f}") if y < 10 else str(_round_half_up(y))
    return f"about once every {s} years"
