"""NVD: vulnerabilities for a named product and version (public API, via the guard)."""

from app.config import settings
from app.guard import OutboundClient
from app.tools.base import Registry, Source, as_data, iso_date, now_iso

URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"


def detail_url(cve_id: str) -> str:
    return f"https://nvd.nist.gov/vuln/detail/{cve_id}"


def _score(metrics: dict) -> tuple[float | None, str | None]:
    for key in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        for m in metrics.get(key) or []:
            data = m.get("cvssData") or {}
            return data.get("baseScore"), data.get("baseSeverity") or m.get("baseSeverity")
    return None, None


def search(outbound: OutboundClient, registry: Registry, keyword: str, limit: int = 10) -> str:
    """CVEs whose description matches the keyword, newest first."""
    registry.cve_lookups += 1
    headers = {"apiKey": settings.nvd_api_key} if settings.nvd_api_key else None
    page = 50
    # NVD lists matches oldest first, so read the total, then the last page.
    res = outbound.get(URL, tool="nvd", query=keyword,
                       params={"keywordSearch": keyword, "resultsPerPage": page}, headers=headers)
    if res.status_code != 200:
        return as_data("web_content", {"error": f"NVD returned status {res.status_code}."})
    total = int(res.json().get("totalResults") or 0)
    if total > page:
        res = outbound.get(URL, tool="nvd", query=keyword, headers=headers,
                           params={"keywordSearch": keyword, "resultsPerPage": page, "startIndex": total - page})
        if res.status_code != 200:
            return as_data("web_content", {"error": f"NVD returned status {res.status_code}."})
    vulns = [v["cve"] for v in res.json().get("vulnerabilities", [])]
    vulns.sort(key=lambda c: c.get("published", ""), reverse=True)
    out = []
    for cve in vulns[:limit]:
        desc = next((d["value"] for d in cve.get("descriptions", []) if d.get("lang") == "en"), "")
        score, severity = _score(cve.get("metrics") or {})
        url = detail_url(cve["id"])
        registry.add(Source(citation=url, origin="external", source_type="vuln_feed", source_name="NVD",
                            published_at=iso_date(cve.get("published")), retrieved_at=now_iso()))
        out.append({"citation": url, "cve": cve["id"], "published": cve.get("published", "")[:10],
                    "cvss": score, "severity": severity, "description": desc[:400]})
    return as_data("web_content", {"keyword": keyword, "total_matches": total, "newest": out})
