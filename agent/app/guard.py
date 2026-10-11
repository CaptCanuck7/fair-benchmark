"""Outbound guard (AGENT_BUILD.md section 8).

Every outbound request from the agent, other than to the Claude API, goes
through `OutboundClient`, which asks `Guard` first and logs every attempt,
allowed or blocked, before anything is sent. This is deterministic code with
no language model involved. Prompts tell the model to search in generic terms;
this module is what enforces it.

Checks, in order:
1. External access is turned on (AGENT_EXTERNAL_ENABLED).
2. URLs are normalised first: a path holding an encoded dot, slash or
   backslash (or a literal backslash) is refused, dot segments are resolved,
   and every later check runs on the normalised URL, which is what is sent.
3. URLs use https and point at an allowlisted domain (or a subdomain of one),
   or start with one of the fixed feed URLs.
4. Queries are at most 120 characters. For hosts other than the fixed feeds,
   so is a URL's decoded query string, and the whole URL is at most 500.
5. Neither the query nor the URL (raw and percent-decoded) contains a register
   or evidence identifier (asset and risk IDs, tickets, incident and finding
   IDs, people's names, business units, environments, asset names), ignoring
   case and treating spaces, hyphens and underscores between its parts alike.
6. A query naming a vendor is sent only if the analyst approved that exact query.

Log entries are redacted: identifiers are replaced with "[asset_id]" and so
on, so the outbound log never holds internal information.
"""

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import unquote_plus, urlsplit, urlunsplit

import httpx

MAX_QUERY_LENGTH = 120
MAX_URL_LENGTH = 500
MAX_REDIRECTS = 3
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
# Percent-decoding passes before the identifier check: enough for double and
# triple encoding, bounded so a crafted URL can't loop.
MAX_DECODE_PASSES = 4
# An encoded dot, slash or backslash in a path could be decoded into a
# different path after the check, so such paths are refused outright.
ENCODED_SEPARATOR = re.compile(r"%(2e|2f|5c)", re.IGNORECASE)
# Inside an identifier, any run of these separates its parts.
SEPARATOR_RUN = re.compile(r"[\s_-]+")

# Feeds the evidence tools read, allowed even if their domains are removed
# from ALLOWED_DOMAINS. Matched as URL prefixes, not whole hosts.
FIXED_FEEDS = (
    "https://services.nvd.nist.gov/rest/json/",
    "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",
    "https://api.first.org/data/v1/epss",
    "https://raw.githubusercontent.com/mitre/cti/",
)


@dataclass(frozen=True)
class Identifier:
    kind: str
    value: str


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str | None = None

    @staticmethod
    def ok() -> "Decision":
        return Decision(True)


class Blocked(Exception):
    """An outbound request the guard refused. `reason` is a short code."""

    def __init__(self, reason: str):
        super().__init__(f"Outbound request blocked: {reason}")
        self.reason = reason


def _host_allowed(host: str, domains: Iterable[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def _remove_dot_segments(path: str) -> str:
    """Resolve "." and ".." in a URL path (RFC 3986 section 5.2.4), never above the root."""
    out: list[str] = []
    for seg in path.split("/"):
        if seg == "..":
            if len(out) > 1:
                out.pop()
        elif seg != ".":
            out.append(seg)
    if path.endswith(("/.", "/..")):
        out.append("")
    return "/".join(out) or "/"


def _decoded(text: str) -> str:
    """Percent-decode (with "+" as a space) until the text stops changing."""
    for _ in range(MAX_DECODE_PASSES):
        nxt = unquote_plus(text)
        if nxt == text:
            break
        text = nxt
    return text


class Guard:
    def __init__(
        self,
        allowed_domains: Iterable[str],
        identifiers: Iterable[Identifier] = (),
        external_enabled: bool = True,
        vendor_names: Iterable[str] = (),
        approved_queries: Iterable[str] = (),
    ):
        self.allowed_domains = tuple(d.lower().lstrip(".") for d in allowed_domains if d)
        self.external_enabled = external_enabled
        self.approved_queries = {q.strip() for q in approved_queries}
        self._identifiers = self._compile(list(identifiers))
        self._vendors = self._compile([Identifier("vendor", v) for v in vendor_names])

    @staticmethod
    def _compile(items: list[Identifier]) -> list[tuple[str, re.Pattern]]:
        """One pattern per kind. Longest values first, so "Asset-4120" isn't
        reported as "Asset-412". Bounded by non-alphanumerics, so "Nova" doesn't
        match inside "renovate". A run of spaces, hyphens or underscores in a
        value matches any such run, so "ASSET 4120" and "ASSET_4120" match
        "ASSET-4120"."""
        by_kind: dict[str, list[str]] = {}
        for item in items:
            value = item.value.strip()
            if value:
                by_kind.setdefault(item.kind, []).append(value)

        def pattern(value: str) -> str:
            return r"[\s_-]+".join(re.escape(part) for part in SEPARATOR_RUN.split(value))

        out = []
        for kind, values in by_kind.items():
            alts = "|".join(pattern(v) for v in sorted(set(values), key=len, reverse=True))
            out.append((kind, re.compile(rf"(?<![0-9A-Za-z])(?:{alts})(?![0-9A-Za-z])", re.IGNORECASE)))
        return out

    def _identifier_in(self, text: str) -> str | None:
        for kind, pattern in self._identifiers:
            if pattern.search(text):
                return kind
        return None

    def redact(self, text: str | None) -> str | None:
        if text is None:
            return None
        patterns = self._identifiers + self._vendors
        # An identifier hidden by percent-encoding is redacted in decoded form,
        # so the log never holds it in either form.
        decoded = _decoded(text)
        if decoded != text and any(p.search(decoded) for _, p in patterns):
            text = decoded
        for kind, pattern in patterns:
            text = pattern.sub(f"[{kind}]", text)
        return text

    def check_query(self, query: str) -> Decision:
        if not self.external_enabled:
            return Decision(False, "external_disabled")
        q = query.strip()
        if not q:
            return Decision(False, "empty_query")
        if len(q) > MAX_QUERY_LENGTH:
            return Decision(False, "query_too_long")
        kind = self._identifier_in(q)
        if kind:
            return Decision(False, f"identifier:{kind}")
        if any(p.search(q) for _, p in self._vendors) and q not in self.approved_queries:
            return Decision(False, "vendor_name_needs_approval")
        return Decision.ok()

    def check_url(self, url: str) -> Decision:
        return self.prepare_url(url)[1]

    def prepare_url(self, url: str) -> tuple[str, Decision]:
        """Normalise a URL and check it. Returns the normalised URL, which is
        the exact string every check ran on and the one to send."""
        if not self.external_enabled:
            return url, Decision(False, "external_disabled")
        try:
            parts = urlsplit(url)
            host = (parts.hostname or "").lower()
            port = parts.port
        except ValueError:
            return url, Decision(False, "invalid_url")
        if parts.scheme.lower() != "https":
            return url, Decision(False, "not_https")
        if parts.username or parts.password or (port not in (None, 443)):
            return url, Decision(False, "invalid_url")
        if "\\" in parts.path or ENCODED_SEPARATOR.search(parts.path):
            return url, Decision(False, "encoded_path")
        # Resolve dot segments, drop the fragment (never sent), and let httpx
        # apply its own normalisation, so the string checked is the string sent.
        try:
            rebuilt = urlunsplit(("https", parts.netloc.lower(), _remove_dot_segments(parts.path or "/"),
                                  parts.query, ""))
            normalized = str(httpx.URL(rebuilt))
            final = urlsplit(normalized)
        except (ValueError, httpx.InvalidURL):
            return url, Decision(False, "invalid_url")
        if "\\" in final.path or ENCODED_SEPARATOR.search(final.path):
            return normalized, Decision(False, "encoded_path")

        fixed = any(normalized.startswith(prefix) for prefix in FIXED_FEEDS)
        if not fixed and not _host_allowed((final.hostname or "").lower(), self.allowed_domains):
            return normalized, Decision(False, "host_not_allowed")
        raw = f"{final.path}?{final.query}"
        decoded_query = _decoded(final.query)
        # Fixed feed URLs are built by code, and some are long (EPSS for 20 CVEs).
        if not fixed:
            if len(normalized) > MAX_URL_LENGTH:
                return normalized, Decision(False, "url_too_long")
            if len(decoded_query) > MAX_QUERY_LENGTH:
                return normalized, Decision(False, "url_query_too_long")
        # Identifiers can leak through paths and query strings, encoded or not.
        kind = self._identifier_in(raw) or self._identifier_in(f"{_decoded(final.path)}?{decoded_query}")
        if kind:
            return normalized, Decision(False, f"identifier:{kind}")
        return normalized, Decision.ok()


@dataclass
class LogEntry:
    tool: str
    destination: str
    query: str | None
    allowed: bool
    blocked_reason: str | None
    agent_run_id: str | None = None


LogSink = Callable[[LogEntry], None]


class OutboundClient:
    """The single path for outbound HTTP from the agent (except the Claude API).

    The log entry is written before the request is sent. If logging fails, the
    request is not sent.
    """

    def __init__(self, guard: Guard, log: LogSink, http: httpx.Client | None = None,
                 agent_run_id: str | None = None):
        self.guard, self.log, self.agent_run_id = guard, log, agent_run_id
        self.http = http or httpx.Client(timeout=20.0, headers={"User-Agent": "fair-workbench-agent"})

    def _record(self, tool: str, destination: str, query: str | None, decision: Decision) -> None:
        self.log(LogEntry(
            tool=tool,
            destination=self.guard.redact(destination) or "",
            query=self.guard.redact(query),
            allowed=decision.allowed,
            blocked_reason=decision.reason,
            agent_run_id=self.agent_run_id,
        ))

    def check_search(self, tool: str, destination: str, query: str) -> Decision:
        """Check and log a search the agent doesn't send itself (for example one
        run through the Claude API's web search tool). Raises Blocked if refused."""
        decision = self.guard.check_query(query)
        self._record(tool, destination, query, decision)
        if not decision.allowed:
            raise Blocked(decision.reason or "blocked")
        return decision

    def get(self, url: str, *, tool: str, query: str | None = None, params: dict | None = None,
            max_bytes: int = DEFAULT_MAX_BYTES, headers: dict | None = None) -> httpx.Response:
        """GET a URL after the guard allows it. Redirects are followed only
        through the guard, and the body is capped at `max_bytes`."""
        target = str(httpx.URL(url, params=params)) if params else url
        for _hop in range(MAX_REDIRECTS + 1):
            # Send exactly the normalised URL the guard checked, on every hop.
            target, decision = self.guard.prepare_url(target)
            if decision.allowed and query is not None:
                decision = self.guard.check_query(query)
            self._record(tool, target, query, decision)
            if not decision.allowed:
                raise Blocked(decision.reason or "blocked")

            with self.http.stream("GET", target, headers=headers, follow_redirects=False) as res:
                if res.is_redirect and "location" in res.headers:
                    target = str(res.url.join(res.headers["location"]))
                    query = None  # the query was checked on the first hop
                    continue
                body = bytearray()
                for chunk in res.iter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise Blocked("response_too_large")
                # iter_bytes() has already decoded the body, so drop the headers
                # that describe the encoded form.
                kept = [(k, v) for k, v in res.headers.multi_items()
                        if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")]
                return httpx.Response(res.status_code, headers=kept, content=bytes(body), request=res.request)
        raise Blocked("too_many_redirects")
