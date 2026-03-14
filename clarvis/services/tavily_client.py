"""Lazy TavilyClient singleton.

Provides a shared TavilyClient instance that initializes on first call.
Requires TAVILY_API_KEY in environment (loaded from .env by daemon startup).
"""

import logging
import os

logger = logging.getLogger(__name__)

_client = None


def get_tavily_client():
    """Lazy TavilyClient singleton. Returns None if no API key."""
    global _client
    if _client is not None:
        return _client

    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        logger.debug("TAVILY_API_KEY not set — web search disabled")
        return None

    from tavily import TavilyClient

    _client = TavilyClient(api_key=api_key)
    logger.info("Tavily client initialized")
    return _client
