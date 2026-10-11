"""Reference library refresh (section 7). The agent reads the allowlisted
report pages and proposes figures; an analyst approves each before use.

Each proposed entry is checked in code: its URL must be a page fetched in this
run, its quote must appear on that page, and its value must appear in the
quote. Entries that fail are dropped and listed, never proposed.
"""

import re

from pydantic import BaseModel

from app.llm import LLM, LLMResult
from app.schemas import LibraryOutput, LibraryRequest
from app.tasks.common import load_prompt
from app.tools.base import Registry
from app.tools.toolbox import Toolbox

PROMPT_VERSION = "library.v1"
MAX_TOOL_CALLS = 12
MAX_SECONDS = 180.0

NUMBER = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(million|billion|thousand|%|percent)?", re.IGNORECASE)
SCALE = {"thousand": 1e3, "million": 1e6, "billion": 1e9}


class LibraryResult(BaseModel):
    entries: list[dict]
    rejected: list[dict]
    tool_calls: int


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


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


def value_in(value: float, quote: str) -> bool:
    return any(abs(n - value) <= max(abs(value) * 0.005, 1e-9) for n in numbers_in(quote))


def check(out: LibraryOutput, registry: Registry) -> tuple[list[dict], list[dict]]:
    entries, rejected = [], []
    for e in out.entries:
        src = registry.get(e.url)
        reason = None
        if src is None or src.text is None:
            reason = "The page wasn't fetched in this run."
        elif _norm(e.quote) not in _norm(src.text):
            reason = "The quote doesn't appear on the page."
        elif not value_in(e.value, e.quote):
            reason = "The value doesn't appear in the quote."
        if reason:
            rejected.append({"metric": e.metric, "url": e.url, "reason": reason})
            continue
        entries.append({**e.model_dump(), "url": src.citation, "retrieved_at": src.retrieved_at})
    return entries, rejected


def run(llm: LLM, req: LibraryRequest, toolbox: Toolbox) -> LLMResult[LibraryResult]:
    have = "\n".join(f"- {x['metric']} ({x['edition']})" for x in req.existing) or "- none yet"
    user = f"Entries already in the library (don't propose these again):\n{have}\n\nFind figures and return the JSON."
    res = llm.tool_loop(load_prompt(PROMPT_VERSION), user, LibraryOutput, toolbox.definitions(), toolbox.execute,
                        max_calls=MAX_TOOL_CALLS, max_seconds=MAX_SECONDS, effort="medium")
    entries, rejected = check(res.output, toolbox.registry)
    return LLMResult(output=LibraryResult(entries=entries, rejected=rejected, tool_calls=res.tool_calls),
                     usage=res.usage, attempts=res.attempts, tool_calls=res.tool_calls)
