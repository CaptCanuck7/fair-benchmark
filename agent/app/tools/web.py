"""Allowlisted web search and page fetch.

Search: the guard checks and logs the exact query before anything is sent.
Only then does a separate, minimal Claude API request run the API's own web
search tool, limited to the allowed domains, with nothing in its context but
that query, so no register or evidence detail can reach a search. The query
the search actually ran is checked and logged too, and results are dropped if
it fails the guard.

Fetch: pages are read with the guard's OutboundClient (allowlisted hosts,
https only, redirects re-checked, size capped) and reduced to plain text.
"""

import re
from html.parser import HTMLParser
from typing import Any

from app.guard import Blocked, OutboundClient
from app.llm import FALLBACK_BETA
from app.tools.base import Registry, Source, as_data, iso_date, now_iso

SEARCH_TOOL = "web_search_20250305"
SEARCH_DESTINATION = "api.anthropic.com (web search)"
PAGE_TEXT_LIMIT = 12_000  # characters returned to the model per page
KEEP_TEXT_LIMIT = 400_000  # characters kept for checks (library refresh)


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form"}
    BLOCK = {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "br", "section", "article", "td"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    """(title, text) with scripts, styles and navigation removed."""
    p = _Text()
    p.feed(html)
    text = re.sub(r"[ \t\r\f\v]+", " ", "".join(p.parts))
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return p.title.strip(), text


def search(outbound: OutboundClient, registry: Registry, client: Any, model: str, query: str,
           allowed_domains: tuple[str, ...], max_results: int = 8) -> str:
    """Run one guarded web search and return its results."""
    outbound.check_search("web_search", SEARCH_DESTINATION, query)  # logs; raises Blocked if refused
    response = client.beta.messages.create(
        model=model, max_tokens=4000,
        system="Run exactly one web search for the user's query, word for word, then list what you found.",
        messages=[{"role": "user", "content": f"Search the web for: {query}"}],
        tools=[{"type": SEARCH_TOOL, "name": "web_search", "max_uses": 1, "allowed_domains": list(allowed_domains)}],
        betas=[FALLBACK_BETA], fallbacks="default",
    )
    results: dict[str, dict] = {}
    for block in response.content:
        kind = getattr(block, "type", None)
        if kind == "server_tool_use":
            ran = str((block.input or {}).get("query", ""))
            if ran.strip() != query.strip():
                # The search ran a different wording: check and log that too.
                outbound.check_search("web_search (as run)", SEARCH_DESTINATION, ran)
        elif kind == "web_search_tool_result":
            content = block.content
            if not isinstance(content, list):  # an error object
                return as_data("web_content", {"error": getattr(content, "error_code", "search failed")})
            for r in content:
                results.setdefault(r.url, {"title": r.title, "url": r.url, "page_age": getattr(r, "page_age", None),
                                           "snippets": []})
        elif kind == "text":
            for c in getattr(block, "citations", None) or []:
                if getattr(c, "url", None) in results and len(results[c.url]["snippets"]) < 3:
                    results[c.url]["snippets"].append(getattr(c, "cited_text", ""))
    out = []
    for r in list(results.values())[:max_results]:
        registry.add(Source(citation=r["url"], origin="external", source_type="web", source_name=r["title"] or r["url"],
                            published_at=iso_date(r["page_age"]), retrieved_at=now_iso()))
        out.append({"citation": r["url"], **r})
    return as_data("web_content", {"query": query, "results": out,
                                   "note": None if out else "No results on the allowed sites."})


def fetch(outbound: OutboundClient, registry: Registry, url: str, *, keep_text: bool = False) -> str:
    """Read one page from an allowed site as plain text."""
    res = outbound.get(url, tool="web_fetch", max_bytes=8 * 1024 * 1024)
    ctype = res.headers.get("content-type", "")
    if res.status_code != 200:
        return as_data("web_content", {"url": url, "error": f"The site returned status {res.status_code}."})
    if "pdf" in ctype:
        return as_data("web_content", {"url": url, "error": "This is a PDF, which this tool can't read. "
                                                            "Look for the figure on a web page instead."})
    title, text = html_to_text(res.text) if "html" in ctype or not ctype else ("", res.text)
    published = None
    if m := re.search(r'"datePublished"\s*:\s*"([^"]+)"', res.text) or \
            re.search(r'article:published_time"\s+content="([^"]+)"', res.text):
        published = iso_date(m.group(1))
    registry.add(Source(citation=url, origin="external", source_type="web", source_name=title or url,
                        published_at=published, retrieved_at=now_iso(),
                        text=text[:KEEP_TEXT_LIMIT] if keep_text else None))
    if keep_text and registry.sources[url].text is None:
        registry.sources[url].text = text[:KEEP_TEXT_LIMIT]
    return as_data("web_content", {"citation": url, "title": title, "published": published,
                                   "text": text[:PAGE_TEXT_LIMIT],
                                   "truncated": len(text) > PAGE_TEXT_LIMIT})


def blocked_message(reason: str) -> str:
    """A guard refusal as a tool error the model can act on."""
    return (f"The outbound guard blocked this request ({reason}). Search in generic terms, without names, IDs "
            "or other details from the register or internal records.")
