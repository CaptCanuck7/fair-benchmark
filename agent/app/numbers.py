"""Reading numbers out of source text, shared by the library refresh (is the
value in the quote?) and evidence gathering (is the value in the record?)."""

import re

NUMBER = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(million|billion|thousand|%|percent)?", re.IGNORECASE)
SCALE = {"thousand": 1e3, "million": 1e6, "billion": 1e9}


def numbers_in(text: str) -> list[float]:
    """Every number in the text, read both as written and with its scale word."""
    out = []
    for m in NUMBER.finditer(text):
        n = float(m.group(1).replace(",", ""))
        out.append(n)
        word = (m.group(2) or "").lower()
        if word in SCALE:
            out.append(n * SCALE[word])
    return out


def matches(value: float, n: float) -> bool:
    return abs(n - value) <= max(abs(value) * 0.005, 1e-9)


def value_in(value: float, quote: str) -> bool:
    return any(matches(value, n) for n in numbers_in(quote))


def value_in_record(value: float, fields: dict) -> bool:
    """Whether the value is one of the record's numbers: a numeric cell, or a
    number written in a text cell (a notes sentence, say)."""
    for cell in fields.values():
        if isinstance(cell, bool) or cell is None:
            continue
        if isinstance(cell, (int, float)):
            if matches(value, float(cell)):
                return True
        elif value_in(value, str(cell)):
            return True
    return False
