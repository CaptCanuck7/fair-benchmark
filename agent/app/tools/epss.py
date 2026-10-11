"""EPSS: the probability a CVE is exploited in the next 30 days (FIRST public API, via the guard)."""

from app.guard import OutboundClient
from app.tools.base import Registry, Source, as_data, iso_date, now_iso
from app.tools.kev import CVE

URL = "https://api.first.org/data/v1/epss"


def score_url(cve_id: str) -> str:
    return f"{URL}?cve={cve_id}"


def scores(outbound: OutboundClient, registry: Registry, cve_ids: list[str]) -> str:
    registry.cve_lookups += 1
    ids = [c.strip().upper() for c in cve_ids if CVE.match(c.strip().upper())][:20]
    if not ids:
        return as_data("web_content", {"error": "Give CVE IDs such as CVE-2024-12345."})
    res = outbound.get(URL, tool="epss", params={"cve": ",".join(ids)})
    if res.status_code != 200:
        return as_data("web_content", {"error": f"EPSS returned status {res.status_code}."})
    out = []
    for row in res.json().get("data", []):
        url = score_url(row["cve"])
        registry.add(Source(citation=url, origin="external", source_type="vuln_feed", source_name="FIRST EPSS",
                            published_at=iso_date(row.get("date")), retrieved_at=now_iso()))
        out.append({"citation": url, "cve": row["cve"], "epss": float(row.get("epss", 0)),
                    "percentile": float(row.get("percentile", 0)), "date": row.get("date"),
                    "meaning": "Estimated probability of exploitation in the next 30 days."})
    missing = sorted(set(ids) - {r["cve"] for r in out})
    return as_data("web_content", {"scores": out, "no_score": missing})
