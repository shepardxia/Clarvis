"""Web search, extract, sitemap, and research command handlers."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import CommandHandlers


def web_search(
    self: CommandHandlers,
    *,
    query: str,
    limit: int = 5,
    search_depth: str = "basic",
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    **kw,
) -> str | dict:
    """Search the web for a query and return summarized results."""
    client = self._get_service("tavily")
    if client is None:
        return {"error": "Web search not available (TAVILY_API_KEY not set or tavily not installed)"}
    try:
        response = client.search(
            query=query,
            max_results=limit,
            search_depth=search_depth,
            include_domains=include_domains,
            exclude_domains=exclude_domains,
            **kw,
        )
        results = response.get("results", [])
        if not results:
            return "No results found."
        lines = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "Untitled")
            snippet = r.get("content", "")
            url = r.get("url", "")
            lines.append(f"{i}. {title}\n   {snippet}\n   {url}")
        return "\n\n".join(lines)
    except Exception as e:
        return {"error": str(e)}


def web_extract(self: CommandHandlers, *, urls: list[str], **kw) -> str | dict:
    """Extract content from one or more URLs."""
    client = self._get_service("tavily")
    if client is None:
        return {"error": "Web search not available (TAVILY_API_KEY not set or tavily not installed)"}
    try:
        return client.extract(urls=urls, **kw)
    except Exception as e:
        return {"error": str(e)}


def web_map(
    self: CommandHandlers, *, url: str, limit: int | None = None, instructions: str | None = None, **kw
) -> str | dict:
    """Get a sitemap/URL list from a base URL."""
    client = self._get_service("tavily")
    if client is None:
        return {"error": "Web search not available (TAVILY_API_KEY not set or tavily not installed)"}
    try:
        return client.map(url=url, limit=limit, instructions=instructions, **kw)
    except Exception as e:
        return {"error": str(e)}


_RESEARCH_POLL_INTERVAL = 2.0
_RESEARCH_POLL_TIMEOUT = 300.0


def web_research(
    self: CommandHandlers,
    *,
    input: str,
    model: str = "auto",
    **kw,
) -> str | dict:
    """Deep multi-step research on a topic. Slower than web_search but synthesizes across multiple sources."""
    client = self._get_service("tavily")
    if client is None:
        return {"error": "Web search not available (TAVILY_API_KEY not set or tavily not installed)"}
    try:
        response = client.research(input=input, model=model, **kw)
        request_id = response.get("request_id")
        if not request_id:
            return response
        deadline = time.monotonic() + _RESEARCH_POLL_TIMEOUT
        while time.monotonic() < deadline:
            time.sleep(_RESEARCH_POLL_INTERVAL)
            result = client.get_research(request_id)
            if result.get("content"):
                return result["content"]
        return {"error": f"Research timed out after {_RESEARCH_POLL_TIMEOUT}s", "request_id": request_id}
    except Exception as e:
        return {"error": str(e)}


COMMANDS: list[str] = [
    "web_search",
    "web_extract",
    "web_map",
    "web_research",
]
