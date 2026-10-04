"""Split the register's Risk Analysis text into its labeled sections."""

import re

# Label as written in the register -> key used in the stored sections.
LABELS = {
    "risk statement": "risk_statement",
    "detailed risk analysis": "detailed_analysis",
    "baseline controls": "baseline_controls",
    "exploit paths": "exploit_paths",
}

# A label counts only at the start of a paragraph (start of the text or of a line).
_LABEL_RE = re.compile(
    r"^[ \t]*(Risk Statement|Detailed Risk Analysis|Baseline Controls|Exploit Paths)[ \t]*:",
    re.IGNORECASE | re.MULTILINE,
)


def split_sections(text: str | None) -> tuple[dict[str, str], bool]:
    """Return (sections, structured).

    Structured text gives a dict keyed by `LABELS` values, plus `preamble` for any
    text before the first label. Text with no labels gives {"raw": text} and
    structured=False. A label that appears twice has its parts joined.
    """
    text = (text or "").replace("\r\n", "\n").strip()
    matches = list(_LABEL_RE.finditer(text))
    if not matches:
        return ({"raw": text} if text else {}), False

    sections: dict[str, str] = {}
    preamble = text[: matches[0].start()].strip()
    if preamble:
        sections["preamble"] = preamble
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        key = LABELS[m.group(1).lower()]
        body = text[m.end():end].strip()
        sections[key] = f"{sections[key]}\n\n{body}".strip() if key in sections else body
    return sections, True
