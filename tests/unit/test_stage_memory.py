"""Tests for stage_memory MCP tool."""

import json
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from fastmcp import Client

from clarvis.mcp.server import STANDARD_TOOLS, create_app


@pytest.fixture
def staging_dir(tmp_path):
    return tmp_path / "staging"


@pytest.fixture
def daemon(staging_dir):
    d = MagicMock()
    d.staging_dir = staging_dir
    d.hindsight_store = None
    d.hindsight_backend = None
    d.cognee_backend = None
    d.channel_manager = None
    return d


@pytest_asyncio.fixture
async def client(daemon):
    app = create_app(daemon, STANDARD_TOOLS)
    async with Client(app) as c:
        yield c


class TestStageMemory:
    @pytest.mark.asyncio
    async def test_stages_summary(self, client, staging_dir):
        result = await client.call_tool(
            "stage_memory", {"summary": "Learned about Pi skill format and session management."}
        )
        assert "Queued" in result.data

        queue_file = staging_dir / "remember_queue.json"
        assert queue_file.exists()
        items = json.loads(queue_file.read_text())
        assert len(items) == 1
        assert "Pi skill format" in items[0]["summary"]

    @pytest.mark.asyncio
    async def test_appends_to_existing_queue(self, daemon, staging_dir):
        staging_dir.mkdir(parents=True, exist_ok=True)
        queue_file = staging_dir / "remember_queue.json"
        queue_file.write_text(json.dumps([{"summary": "first", "timestamp": "t1"}]))

        app = create_app(daemon, STANDARD_TOOLS)
        async with Client(app) as c:
            await c.call_tool("stage_memory", {"summary": "second"})

        items = json.loads(queue_file.read_text())
        assert len(items) == 2
