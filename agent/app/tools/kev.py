"""CISA Known Exploited Vulnerabilities: is a CVE being exploited? (public JSON feed, via the guard)"""

import re
import time

from app.guard import OutboundClient
from app.tools.base import Registry, Source, as_data, iso_date, now_iso

FEED = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
CACHE_SECONDS = 24 * 3600
CVE = re.compile(r"^CVE-\d{4}-\d{4,}$")

_cache: dict = {"at": 0.0, "by_cve": None}


def catalog_url(cve_id: str) -> str:
    return f"https://www.cisa.gov/known-exploited-vulnerabilities-catalog?search_api_fulltext={cve_id}"


def _catalog(outbound: OutboundClient) -> dict[str, dict]:
    if _cache["by_cve"] is None or time.monotonic() - _cache["at"] > CACHE_SECONDS:
        res = outbound.get(FEED, tool="kev", max_bytes=20 * 1024 * 1024)
        res.raise_for_status()
        _cache["by_cve"] = {v["cveID"]: v for v in res.json().get("vulnerabilities", [])}
        _cache["at"] = time.monotonic()
    return _cache["by_cve"]


def check(outbound: OutboundClient, registry: Registry, cve_ids: list[str]) -> str:
    registry.cve_lookups += 1
    ids = [c.strip().upper() for c in cve_ids if CVE.match(c.strip().upper())][:20]
    if not ids:
        return as_data("web_content", {"error": "Give CVE IDs such as CVE-2024-12345."})
    by_cve = _catalog(outbound)
    out = []
    for cve in ids:
        v = by_cve.get(cve)
        if v is None:
            out.append({"cve": cve, "in_catalog": False})
            continue
        url = catalog_url(cve)
        registry.add(Source(citation=url, origin="external", source_type="vuln_feed",
                            source_name="CISA Known Exploited Vulnerabilities catalog",
                            published_at=iso_date(v.get("dateAdded")), retrieved_at=now_iso()))
        out.append({"citation": url, "cve": cve, "in_catalog": True, "date_added": v.get("dateAdded"),
                    "name": v.get("vulnerabilityName"), "ransomware_use": v.get("knownRansomwareCampaignUse"),
                    "summary": (v.get("shortDescription") or "")[:300]})
    return as_data("web_content", {"results": out})
