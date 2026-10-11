"""MITRE ATT&CK: techniques relevant to a missing control or an attack vector.

The Enterprise STIX bundle is downloaded once through the guard and indexed in
memory for the life of the agent process (it is about 40 MB, so it isn't
fetched per task)."""

import re
import threading

from app.guard import OutboundClient
from app.tools.base import Registry, Source, as_data, iso_date, now_iso

BUNDLE = "https://raw.githubusercontent.com/mitre/cti/master/enterprise-attack/enterprise-attack.json"
MAX_BYTES = 120 * 1024 * 1024

_index: list[dict] | None = None
_lock = threading.Lock()


def build_index(bundle: dict) -> list[dict]:
    out = []
    for o in bundle.get("objects", []):
        if o.get("type") != "attack-pattern" or o.get("revoked") or o.get("x_mitre_deprecated"):
            continue
        ref = next((r for r in o.get("external_references", []) if r.get("source_name") == "mitre-attack"), None)
        if not ref:
            continue
        desc = re.sub(r"\(Citation:[^)]*\)", "", o.get("description", "")).strip()
        out.append({
            "id": ref["external_id"], "name": o.get("name", ""), "url": ref.get("url"),
            "tactics": [k["phase_name"] for k in o.get("kill_chain_phases", [])],
            "summary": desc.split("\n")[0][:400], "modified": (o.get("modified") or "")[:10],
            "_text": f"{o.get('name', '')} {desc}".lower(),
        })
    return out


def _load(outbound: OutboundClient) -> list[dict]:
    global _index
    with _lock:
        if _index is None:
            res = outbound.get(BUNDLE, tool="attack", max_bytes=MAX_BYTES)
            res.raise_for_status()
            _index = build_index(res.json())
    return _index


def search(outbound: OutboundClient, registry: Registry, keywords: str, limit: int = 8,
           index: list[dict] | None = None) -> str:
    words = [w for w in re.findall(r"[a-z0-9]+", keywords.lower()) if len(w) > 2]
    if not words:
        return as_data("web_content", {"error": "Give a few descriptive words, such as 'phishing credentials'."})
    techniques = index if index is not None else _load(outbound)

    def score(t: dict) -> int:
        return sum(3 * (w in t["name"].lower()) + (w in t["_text"]) for w in words)

    best = sorted((t for t in techniques if score(t)), key=score, reverse=True)[:limit]
    out = []
    for t in best:
        registry.add(Source(citation=t["url"], origin="external", source_type="framework", source_name="MITRE ATT&CK",
                            published_at=iso_date(t["modified"]), retrieved_at=now_iso()))
        out.append({"citation": t["url"], "technique": t["id"], "name": t["name"], "tactics": t["tactics"],
                    "summary": t["summary"]})
    return as_data("web_content", {"keywords": keywords, "techniques": out})
