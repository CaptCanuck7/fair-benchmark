import httpx
import pytest

from app.guard import FIXED_FEEDS, Blocked, Guard, Identifier, LogEntry, OutboundClient

DOMAINS = ["nvd.nist.gov", "cisa.gov", "first.org", "attack.mitre.org", "cisecurity.org"]

# One example of each identifier class the api builds (app/identifiers.py).
IDENTIFIERS = [
    Identifier("asset_id", "Asset-412"),
    Identifier("risk_id", "TR-6"),
    Identifier("risk_id", "Monitoring Task-5"),
    Identifier("ticket_id", "VUL-20417"),
    Identifier("incident_id", "INC-2026-021"),
    Identifier("finding_id", "FND-1041"),
    Identifier("record_id", "PT-058"),
    Identifier("person", "VP Ben Nakamura"),
    Identifier("person", "Ben Nakamura"),
    Identifier("person", "Nakamura"),
    Identifier("business_unit", "Workplace Services"),
    Identifier("environment", "Excelsior"),
    Identifier("asset_name", "Customer SFTP server 1"),
]


def guard(**kw) -> Guard:
    return Guard(allowed_domains=kw.pop("domains", DOMAINS), identifiers=IDENTIFIERS, **kw)


# --- Queries ---


def test_generic_query_is_allowed():
    assert guard().check_query("end-of-support operating system exploitation rates").allowed


@pytest.mark.parametrize("query, kind", [
    ("exploits for asset-412 sftp", "asset_id"),
    ("TR-6 end of support", "risk_id"),
    ("monitoring task-5 status", "risk_id"),
    ("VUL-20417 remediation", "ticket_id"),
    ("inc-2026-021 brute force", "incident_id"),
    ("FND-1041 operating system", "finding_id"),
    ("pt-058 password spraying", "record_id"),
    ("ben nakamura phishing", "person"),
    ("Nakamura credentials", "person"),
    ("workplace services DLP", "business_unit"),
    ("EXCELSIOR breach", "environment"),
    ("customer sftp server 1 vulnerabilities", "asset_name"),
])
def test_each_identifier_class_is_blocked_ignoring_case(query, kind):
    d = guard().check_query(query)
    assert not d.allowed
    assert d.reason == f"identifier:{kind}"


def test_identifiers_match_whole_tokens_only():
    g = guard()
    assert g.check_query("Asset-4120 is a different asset").allowed
    assert g.check_query("renovated excelsiorly").allowed  # no token boundary around the name
    assert not g.check_query("asset-412, exposed").allowed


def test_long_query_is_blocked():
    g = guard()
    assert g.check_query("x" * 120).allowed
    d = g.check_query("x" * 121)
    assert not d.allowed and d.reason == "query_too_long"


def test_empty_query_is_blocked():
    assert guard().check_query("   ").reason == "empty_query"


def test_vendor_names_need_approval_of_that_exact_query():
    g = guard(vendor_names=["Acme Tickets"])
    assert g.check_query("acme tickets breach 2025").reason == "vendor_name_needs_approval"
    approved = guard(vendor_names=["Acme Tickets"], approved_queries=["acme tickets breach 2025"])
    assert approved.check_query("acme tickets breach 2025").allowed
    assert approved.check_query("acme tickets breach 2026").reason == "vendor_name_needs_approval"


def test_external_disabled_blocks_everything():
    g = guard(external_enabled=False)
    assert g.check_query("tls 1.0 interception risk").reason == "external_disabled"
    assert g.check_url("https://nvd.nist.gov/").reason == "external_disabled"


# --- URLs ---


@pytest.mark.parametrize("url", [
    "https://nvd.nist.gov/vuln/detail/CVE-2024-0001",
    "https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=openssh",
    "https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
    "https://attack.mitre.org/techniques/T1110/",
])
def test_allowlisted_hosts_and_subdomains_are_allowed(url):
    assert guard().check_url(url).allowed


@pytest.mark.parametrize("url, reason", [
    ("https://example.com/", "host_not_allowed"),
    ("https://nvd.nist.gov.evil.com/", "host_not_allowed"),
    ("https://evilnvd.nist.gov.com/", "host_not_allowed"),
    ("https://notcisa.gov/", "host_not_allowed"),
    ("http://nvd.nist.gov/", "not_https"),
    ("https://user:pw@nvd.nist.gov/", "invalid_url"),
    ("https://nvd.nist.gov:8443/", "invalid_url"),
    ("https://api/internal/evidence/assets", "host_not_allowed"),
    ("https://api:8000/internal/evidence/assets", "invalid_url"),
    ("https://169.254.169.254/latest/meta-data", "host_not_allowed"),
])
def test_non_allowlisted_or_unsafe_urls_are_blocked(url, reason):
    d = guard().check_url(url)
    assert not d.allowed and d.reason == reason


def test_fixed_feeds_are_allowed_even_without_their_domains():
    g = guard(domains=[])
    for prefix in FIXED_FEEDS:
        assert g.check_url(prefix).allowed
    assert not g.check_url("https://raw.githubusercontent.com/someone/else/main/x.json").allowed


def test_identifiers_in_url_paths_and_parameters_are_blocked():
    g = guard()
    assert g.check_url("https://nvd.nist.gov/search?q=Asset-412").reason == "identifier:asset_id"
    assert g.check_url("https://cisa.gov/excelsior").reason == "identifier:environment"


def test_redact_replaces_identifiers_with_their_kind():
    assert guard().redact("Asset-412 owned by VP Ben Nakamura") == "[asset_id] owned by [person]"


# --- OutboundClient: logging and the wrapper ---


class Recorder:
    def __init__(self):
        self.entries: list[LogEntry] = []

    def __call__(self, entry: LogEntry) -> None:
        self.entries.append(entry)


def client(handler, rec: Recorder, **kw) -> OutboundClient:
    return OutboundClient(guard(**kw), rec, http=httpx.Client(transport=httpx.MockTransport(handler)),
                          agent_run_id="run-1")


def test_allowed_request_is_logged_then_sent():
    sent = []
    rec = Recorder()

    def handler(req):
        sent.append(str(req.url))
        return httpx.Response(200, json={"ok": True})

    res = client(handler, rec).get("https://services.nvd.nist.gov/rest/json/cves/2.0",
                                   params={"keywordSearch": "openssh"}, tool="nvd", query="openssh")
    assert res.json() == {"ok": True}
    assert len(sent) == 1
    [entry] = rec.entries
    assert entry.allowed and entry.tool == "nvd" and entry.agent_run_id == "run-1"
    assert "keywordSearch=openssh" in entry.destination


def test_blocked_request_is_logged_redacted_and_never_sent():
    rec = Recorder()

    def handler(req):
        raise AssertionError("must not be sent")

    with pytest.raises(Blocked) as exc:
        client(handler, rec).get("https://nvd.nist.gov/search", params={"q": "Asset-412"}, tool="web",
                                 query="Asset-412 exploit")
    assert exc.value.reason == "identifier:asset_id"
    [entry] = rec.entries
    assert not entry.allowed and entry.blocked_reason == "identifier:asset_id"
    assert "Asset-412" not in entry.destination and "Asset-412" not in (entry.query or "")
    assert "[asset_id]" in entry.query


def test_non_allowlisted_host_is_logged_and_blocked():
    rec = Recorder()
    with pytest.raises(Blocked):
        client(lambda r: httpx.Response(200), rec).get("https://example.com/", tool="web")
    assert rec.entries[0].blocked_reason == "host_not_allowed"


def test_redirects_are_followed_only_through_the_guard():
    rec = Recorder()

    def handler(req):
        if req.url.host == "nvd.nist.gov":
            return httpx.Response(302, headers={"location": "https://example.com/elsewhere"})
        raise AssertionError("redirect target must not be fetched")

    with pytest.raises(Blocked) as exc:
        client(handler, rec).get("https://nvd.nist.gov/start", tool="web")
    assert exc.value.reason == "host_not_allowed"
    assert [e.allowed for e in rec.entries] == [True, False]


def test_logging_failure_stops_the_request():
    def failing_log(entry):
        raise RuntimeError("api down")

    def handler(req):
        raise AssertionError("must not be sent")

    c = OutboundClient(guard(), failing_log, http=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(RuntimeError):
        c.get("https://nvd.nist.gov/", tool="web")


def test_oversized_response_is_rejected():
    rec = Recorder()
    big = b"x" * 2048
    with pytest.raises(Blocked) as exc:
        client(lambda r: httpx.Response(200, content=big), rec).get("https://nvd.nist.gov/", tool="web", max_bytes=1024)
    assert exc.value.reason == "response_too_large"


def test_check_search_logs_and_blocks():
    rec = Recorder()
    c = client(lambda r: httpx.Response(200), rec)
    assert c.check_search("web_search", "claude web search", "tls 1.0 interception risk").allowed
    with pytest.raises(Blocked):
        c.check_search("web_search", "claude web search", "Excelsior tls 1.0")
    assert [e.allowed for e in rec.entries] == [True, False]
    assert rec.entries[1].query == "[environment] tls 1.0"


# --- AGENT_FIXES.md fix 2: the URL gaps ---


@pytest.mark.parametrize("url", [
    "https://nvd.nist.gov/search?q=ASSET%2D412",        # encoded hyphen
    "https://nvd.nist.gov/search?q=ASSET%252D412",      # encoded twice
    "https://nvd.nist.gov/search?q=asset+412",          # "+" is a space
    "https://nvd.nist.gov/%41sset-412",                 # encoded letter in the path
])
def test_encoded_identifiers_in_urls_are_blocked(url):
    assert guard().check_url(url).reason == "identifier:asset_id"


@pytest.mark.parametrize("query", ["exploit ASSET 412 sftp", "exploit asset_412 sftp", "exploit asset - 412"])
def test_identifier_separators_are_interchangeable(query):
    assert guard().check_query(query).reason == "identifier:asset_id"


def test_separator_matching_keeps_token_boundaries():
    g = guard()
    assert g.check_query("Asset 4120 is a different asset").allowed
    assert g.check_query("asset_4120 too").allowed
    assert g.check_query("renovated excelsiorly").allowed
    assert g.check_query("ben   nakamura phishing").reason == "identifier:person"


def test_long_urls_are_blocked_on_non_feed_hosts():
    g = guard()
    assert g.check_url("https://nvd.nist.gov/search?q=" + "a" * 121).reason == "url_query_too_long"
    assert g.check_url("https://nvd.nist.gov/search?q=" + "a%20" * 60).reason == "url_query_too_long"
    assert g.check_url("https://nvd.nist.gov/search?q=" + "a" * 100).allowed
    assert g.check_url("https://nvd.nist.gov/" + "p/" * 260).reason == "url_too_long"


@pytest.mark.parametrize("url", [
    "https://raw.githubusercontent.com/mitre/cti/../../someone/repo/main/page.html",
    "https://raw.githubusercontent.com/mitre/cti/./../../someone/repo/main/page.html",
])
def test_dot_segments_cant_escape_a_fixed_feed(url):
    assert guard(domains=[]).check_url(url).reason == "host_not_allowed"


@pytest.mark.parametrize("url", [
    "https://raw.githubusercontent.com/mitre/cti/%2e%2e/%2e%2e/someone/repo/x.json",
    "https://raw.githubusercontent.com/mitre/cti/..%2f..%2fsomeone/x.json",
    "https://raw.githubusercontent.com/mitre/cti/..%5C..%5Csomeone/x.json",
    r"https://nvd.nist.gov/a\..\b",
])
def test_encoded_or_backslash_separators_in_paths_are_refused(url):
    assert guard(domains=["nvd.nist.gov"]).check_url(url).reason == "encoded_path"


def test_real_feed_urls_still_pass():
    g = guard(domains=[])
    cves = ",".join(f"CVE-2024-{i:04d}" for i in range(1, 21))
    for url, params in [
        ("https://services.nvd.nist.gov/rest/json/cves/2.0", {"keywordSearch": "openssh", "resultsPerPage": 50}),
        ("https://services.nvd.nist.gov/rest/json/cves/2.0",
         {"keywordSearch": "windows server 2012 smb", "resultsPerPage": 50, "startIndex": 1950}),
        ("https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json", None),
        ("https://api.first.org/data/v1/epss", {"cve": cves}),
        ("https://raw.githubusercontent.com/mitre/cti/master/enterprise-attack/enterprise-attack.json", None),
    ]:
        target = str(httpx.URL(url, params=params)) if params else url
        assert g.check_url(target).allowed, target


def test_the_client_sends_the_normalised_url_and_logs_blocks():
    sent, rec = [], Recorder()

    def handler(req):
        sent.append(str(req.url))
        return httpx.Response(200, text="ok")

    c = client(handler, rec)
    c.get("https://nvd.nist.gov/a/./b/../c#frag", tool="web_fetch")
    assert sent == ["https://nvd.nist.gov/a/c"] and rec.entries[0].destination == "https://nvd.nist.gov/a/c"
    for url, reason in [("https://nvd.nist.gov/search?q=ASSET%2D412", "identifier:asset_id"),
                        ("https://nvd.nist.gov/search?q=" + "a" * 200, "url_query_too_long"),
                        ("https://raw.githubusercontent.com/mitre/cti/../../x/y", "host_not_allowed")]:
        with pytest.raises(Blocked) as exc:
            c.get(url, tool="web_fetch")
        assert exc.value.reason == reason and rec.entries[-1].blocked_reason == reason
    assert len(sent) == 1
    # The log holds the blocked URL with the decoded identifier redacted.
    assert rec.entries[1].destination == "https://nvd.nist.gov/search?q=[asset_id]"


def test_redirect_to_an_allowlisted_host_is_followed():
    sent, rec = [], Recorder()

    def handler(req):
        sent.append(str(req.url))
        if req.url.host == "nvd.nist.gov":
            return httpx.Response(301, headers={"location": "https://www.cisa.gov/news/../page"})
        return httpx.Response(200, text="done")

    res = client(handler, rec).get("https://nvd.nist.gov/start", tool="web_fetch")
    assert res.text == "done"
    assert sent == ["https://nvd.nist.gov/start", "https://www.cisa.gov/page"]
    assert [e.allowed for e in rec.entries] == [True, True]


def test_an_encoded_identifier_in_a_redirect_is_blocked():
    rec = Recorder()

    def handler(req):
        if req.url.path == "/start":
            return httpx.Response(302, headers={"location": "/next?ref=Asset%5F412"})
        raise AssertionError("must not be sent")

    with pytest.raises(Blocked) as exc:
        client(handler, rec).get("https://nvd.nist.gov/start", tool="web_fetch")
    assert exc.value.reason == "identifier:asset_id"
