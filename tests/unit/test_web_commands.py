"""Tests for web search/extract/map/research daemon commands."""

import asyncio
import threading
from unittest.mock import MagicMock

import pytest

tavily = pytest.importorskip("tavily")

from clarvis.core.commands import web as _web  # noqa: E402


@pytest.fixture
def loop():
    _loop = asyncio.new_event_loop()
    t = threading.Thread(target=_loop.run_forever, daemon=True)
    t.start()
    yield _loop
    _loop.call_soon_threadsafe(_loop.stop)
    t.join(timeout=2)
    _loop.close()


def _make_handlers(loop, **services):
    from clarvis.core.commands import CommandHandlers

    ctx = MagicMock()
    ctx.loop = loop
    ctx.bus = MagicMock()
    ctx.state = MagicMock()
    ctx.config = {}

    return CommandHandlers(
        ctx=ctx,
        session_tracker=MagicMock(),
        refresh=MagicMock(),
        command_server=MagicMock(),
        services=services,
    )


@pytest.fixture
def mock_tavily():
    client = MagicMock()
    client.search.return_value = {
        "results": [
            {"title": "Result One", "content": "First snippet", "url": "https://example.com/1"},
            {"title": "Result Two", "content": "Second snippet", "url": "https://example.com/2"},
        ]
    }
    client.extract.return_value = {"results": [{"url": "https://example.com", "raw_content": "Page content here"}]}
    client.map.return_value = {"results": ["https://example.com/a", "https://example.com/b"]}
    client.research.return_value = {"request_id": "default-id"}
    client.get_research.return_value = {"request_id": "default-id", "content": "Default report"}
    return client


@pytest.fixture
def handlers(loop, mock_tavily):
    return _make_handlers(loop, tavily=lambda: mock_tavily)


# ── web_search ────────────────────────────────────────────────────


class TestWebSearch:
    def test_returns_formatted_results(self, handlers, mock_tavily):
        result = _web.web_search(handlers, query="test query")
        assert "1. Result One" in result
        assert "2. Result Two" in result
        assert "https://example.com/1" in result
        assert "First snippet" in result
        mock_tavily.search.assert_called_once_with(
            query="test query",
            max_results=5,
            search_depth="basic",
            include_domains=None,
            exclude_domains=None,
        )

    def test_custom_limit(self, handlers, mock_tavily):
        _web.web_search(handlers, query="test", limit=3)
        mock_tavily.search.assert_called_once_with(
            query="test",
            max_results=3,
            search_depth="basic",
            include_domains=None,
            exclude_domains=None,
        )

    def test_advanced_search_depth(self, handlers, mock_tavily):
        _web.web_search(handlers, query="test", search_depth="advanced")
        mock_tavily.search.assert_called_once_with(
            query="test",
            max_results=5,
            search_depth="advanced",
            include_domains=None,
            exclude_domains=None,
        )

    def test_include_domains(self, handlers, mock_tavily):
        _web.web_search(handlers, query="test", include_domains=["rateyourmusic.com"])
        mock_tavily.search.assert_called_once_with(
            query="test",
            max_results=5,
            search_depth="basic",
            include_domains=["rateyourmusic.com"],
            exclude_domains=None,
        )

    def test_kwargs_passthrough(self, handlers, mock_tavily):
        _web.web_search(handlers, query="test", time_range="week")
        mock_tavily.search.assert_called_once_with(
            query="test",
            max_results=5,
            search_depth="basic",
            include_domains=None,
            exclude_domains=None,
            time_range="week",
        )

    def test_no_results(self, handlers, mock_tavily):
        mock_tavily.search.return_value = {"results": []}
        result = _web.web_search(handlers, query="obscure query")
        assert result == "No results found."

    def test_service_unavailable(self, loop):
        h = _make_handlers(loop, tavily=lambda: None)
        result = _web.web_search(h, query="test")
        assert isinstance(result, dict)
        assert "error" in result

    def test_no_service_registered(self, loop):
        h = _make_handlers(loop)
        result = _web.web_search(h, query="test")
        assert isinstance(result, dict)
        assert "error" in result

    def test_exception_handling(self, handlers, mock_tavily):
        mock_tavily.search.side_effect = RuntimeError("API timeout")
        result = _web.web_search(handlers, query="test")
        assert isinstance(result, dict)
        assert "API timeout" in result["error"]


# ── web_extract ───────────────────────────────────────────────────


class TestWebExtract:
    def test_returns_raw_dict(self, handlers, mock_tavily):
        result = _web.web_extract(handlers, urls=["https://example.com"])
        assert "results" in result
        mock_tavily.extract.assert_called_once_with(urls=["https://example.com"])

    def test_kwargs_passthrough(self, handlers, mock_tavily):
        _web.web_extract(handlers, urls=["https://example.com"], format="markdown")
        mock_tavily.extract.assert_called_once_with(urls=["https://example.com"], format="markdown")

    def test_service_unavailable(self, loop):
        h = _make_handlers(loop, tavily=lambda: None)
        result = _web.web_extract(h, urls=["https://example.com"])
        assert isinstance(result, dict)
        assert "error" in result

    def test_exception_handling(self, handlers, mock_tavily):
        mock_tavily.extract.side_effect = RuntimeError("Network error")
        result = _web.web_extract(handlers, urls=["https://example.com"])
        assert "Network error" in result["error"]


# ── web_map ───────────────────────────────────────────────────────


class TestWebMap:
    def test_returns_raw_dict(self, handlers, mock_tavily):
        result = _web.web_map(handlers, url="https://docs.example.com")
        assert "results" in result
        mock_tavily.map.assert_called_once_with(url="https://docs.example.com", limit=None, instructions=None)

    def test_limit_and_instructions(self, handlers, mock_tavily):
        _web.web_map(handlers, url="https://docs.example.com", limit=20, instructions="only API pages")
        mock_tavily.map.assert_called_once_with(
            url="https://docs.example.com",
            limit=20,
            instructions="only API pages",
        )

    def test_service_unavailable(self, loop):
        h = _make_handlers(loop, tavily=lambda: None)
        result = _web.web_map(h, url="https://example.com")
        assert isinstance(result, dict)
        assert "error" in result

    def test_exception_handling(self, handlers, mock_tavily):
        mock_tavily.map.side_effect = RuntimeError("DNS failure")
        result = _web.web_map(handlers, url="https://example.com")
        assert "DNS failure" in result["error"]


# ── web_research ─────────────────────────────────────────────────


class TestWebResearch:
    def test_polls_until_content(self, handlers, mock_tavily, monkeypatch):
        """Polls get_research() until content arrives."""
        monkeypatch.setattr(_web, "_RESEARCH_POLL_INTERVAL", 0.01)
        mock_tavily.research.return_value = {"request_id": "abc123"}
        mock_tavily.get_research.side_effect = [
            {"request_id": "abc123"},
            {"request_id": "abc123", "content": "Final report"},
        ]
        result = _web.web_research(handlers, input="test query")
        assert result == "Final report"
        assert mock_tavily.get_research.call_count == 2

    def test_custom_model(self, handlers, mock_tavily):
        mock_tavily.research.return_value = {"request_id": "abc123"}
        mock_tavily.get_research.return_value = {"content": "done"}
        _web.web_research(handlers, input="test", model="pro")
        mock_tavily.research.assert_called_once_with(input="test", model="pro")

    def test_poll_timeout(self, handlers, mock_tavily, monkeypatch):
        """Returns error with request_id if polling exceeds timeout."""
        monkeypatch.setattr(_web, "_RESEARCH_POLL_INTERVAL", 0.01)
        monkeypatch.setattr(_web, "_RESEARCH_POLL_TIMEOUT", 0.15)
        mock_tavily.research.return_value = {"request_id": "abc123"}
        mock_tavily.get_research.return_value = {"request_id": "abc123"}
        result = _web.web_research(handlers, input="slow query")
        assert isinstance(result, dict)
        assert "timed out" in result["error"]
        assert result["request_id"] == "abc123"

    def test_no_request_id_returns_raw(self, handlers, mock_tavily):
        """If research() returns no request_id, return raw response."""
        mock_tavily.research.return_value = {"something": "unexpected"}
        result = _web.web_research(handlers, input="test")
        assert result == {"something": "unexpected"}

    def test_kwargs_passthrough(self, handlers, mock_tavily):
        _web.web_research(handlers, input="test", citation_format="apa")
        mock_tavily.research.assert_called_once_with(
            input="test",
            model="auto",
            citation_format="apa",
        )

    def test_service_unavailable(self, loop):
        h = _make_handlers(loop, tavily=lambda: None)
        result = _web.web_research(h, input="test")
        assert isinstance(result, dict)
        assert "error" in result

    def test_no_service_registered(self, loop):
        h = _make_handlers(loop)
        result = _web.web_research(h, input="test")
        assert isinstance(result, dict)
        assert "error" in result

    def test_exception_handling(self, handlers, mock_tavily):
        mock_tavily.research.side_effect = RuntimeError("Rate limited")
        result = _web.web_research(handlers, input="test")
        assert isinstance(result, dict)
        assert "Rate limited" in result["error"]
