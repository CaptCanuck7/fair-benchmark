"""Figures for report drafts, and the number check (AGENT_BUILD.md section 9.7).

The agent is handed figures already formatted the way the workbench shows them
($1.09M, 86%, 2.8). After it drafts, every number in the text must match a
value in the stored run results or the analysis document, after rounding to
the precision the text shows. One number that doesn't match discards the draft.
"""

import math
import re
from collections.abc import Iterable
from typing import Any

# Chart data and check text are left out: with thousands of points, almost any
# number would match one of them.
SKIP_KEYS = {"exceedanceCurve", "histogram", "curves", "checks", "bins"}
PERCENTILES = r"(?:10|50|90|95|99)"


# --- Formatting, as web/src/lib/format.ts ----------------------------------------


def _trim(x: float) -> str:
    s = f"{x:.0f}" if x >= 100 else f"{x:.1f}" if x >= 10 else f"{x:.2f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def money(v: float | None) -> str | None:
    if v is None or not math.isfinite(v):
        return None
    a = abs(v)
    for scale, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= scale:
            return f"${_trim(a / scale)}{suffix}"
    return f"${round(a)}"


def pct(p: float | None) -> str | None:
    if p is None or not math.isfinite(p):
        return None
    if 0 < p < 0.001:
        return "less than 0.1%"
    x = abs(p) * 100
    return (f"{x:.1f}".removesuffix(".0") if x < 10 else f"{x:.0f}") + "%"


def freq(f: float | None) -> str | None:
    if f is None or not math.isfinite(f):
        return None
    if f >= 10:
        return f"{f:.0f}"
    if f >= 1:
        return f"{f:.1f}".removesuffix(".0")
    if f >= 0.1:
        return f"{f:.2f}"
    return f"{f:.2g}"


# --- The check ------------------------------------------------------------------


def _numbers(obj: Any) -> Iterable[float]:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        if math.isfinite(obj):
            yield float(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k not in SKIP_KEYS:
                yield from _numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _numbers(v)


def allowed_values(results: dict, document: dict) -> set[float]:
    """Every number in the stored results (less chart data) and the document,
    plus the option counts a report may state."""
    states = document.get("states") or []
    values = {abs(v) for v in _numbers(results)}
    values |= {abs(v) for v in _numbers({"settings": document.get("settings"), "states": states})}
    values |= {float(len(states)), float(max(len(states) - 1, 0))}
    return values


# A number as written: optional sign and $, digits with optional thousands
# separators and decimals, then an optional %, K/M/B or scale word.
NUMBER = re.compile(
    r"(?<![\w.])[-−]?\$?(?P<int>\d{1,3}(?:,\d{3})+|\d+)(?P<dec>\.\d+)?"
    r"(?:\s?(?P<pct>%|percent\b)|(?P<suf>[KMB])\b|\s(?P<word>thousand|million|billion)\b)?",
)
SCALE = {"K": 1e3, "M": 1e6, "B": 1e9, "thousand": 1e3, "million": 1e6, "billion": 1e9}


def _strip_labels(text: str, names: Iterable[str]) -> str:
    """Remove text that holds digits but isn't a figure: option and analysis
    names, register IDs, and percentile labels such as P90 or 90th percentile."""
    for name in sorted({n for n in names if n and any(c.isdigit() for c in n)}, key=len, reverse=True):
        text = text.replace(name, " ")
    text = re.sub(r"\b[A-Z]{2,}-\d+\b", " ", text)
    text = re.sub(rf"\b[Pp]{PERCENTILES}\b", " ", text)
    text = re.sub(rf"\b{PERCENTILES}(?:st|nd|rd|th)?[- ]percentile\b", " ", text)
    return text


def _matches(mantissa: float, decimals: int, scale: float, is_pct: bool, values: set[float]) -> bool:
    tol = 0.5 * 10 ** -decimals + 1e-9
    for v in values:
        candidates = (v * 100, v) if is_pct else (v / scale,)
        if any(abs(c - mantissa) <= tol for c in candidates):
            return True
    return False


def unmatched_numbers(texts: Iterable[str | None], results: dict, document: dict,
                      names: Iterable[str] = ()) -> list[str]:
    """The numbers in `texts` that match no value in the run or the document."""
    values = allowed_values(results, document)
    bad: list[str] = []
    for text in texts:
        if not text:
            continue
        for m in NUMBER.finditer(_strip_labels(text, names)):
            whole = m.group("int").replace(",", "")
            dec = m.group("dec") or ""
            mantissa = float(whole + dec)
            decimals = max(len(dec) - 1, 0)
            is_pct = bool(m.group("pct"))
            scale = SCALE.get(m.group("suf") or m.group("word") or "", 1.0)
            # A bare year is a date, not a figure.
            if not (is_pct or dec or scale != 1.0 or "$" in m.group(0)) and 1990 <= mantissa <= 2100:
                continue
            if not _matches(mantissa, decimals, scale, is_pct, values):
                bad.append(m.group(0).strip())
    return bad
