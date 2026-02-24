"""Graphiti temporal knowledge graph backend for the dual memory system.

Uses FalkorDB Lite (embedded graph DB via falkordblite) and Anthropic's
Claude as the LLM client. Episodes are scoped to named datasets; search
is filtered by group_id visibility.
"""

import logging
import os
from pathlib import Path
from typing import Any

from clarvis.core.credentials import get_oauth_token
from clarvis.widget.config import DatasetConfig

logger = logging.getLogger(__name__)

# Default datasets when none are configured.
_DEFAULT_DATASETS: dict[str, DatasetConfig] = {
    "parletre": DatasetConfig(visibility="master"),
    "agora": DatasetConfig(visibility="all"),
}


def _get_api_key() -> str | None:
    """Retrieve Anthropic API key: env var first, then macOS Keychain."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    return get_oauth_token()


class GraphitiBackend:
    """Graphiti temporal knowledge graph backend.

    Manages a single Graphiti instance backed by FalkorDB Lite, with datasets
    mapped to group_ids for visibility scoping.
    """

    def __init__(
        self,
        data_dir: Path,
        dataset_configs: dict[str, DatasetConfig] | None = None,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-6",
    ) -> None:
        self._data_dir = Path(data_dir)
        self._dataset_configs = dataset_configs or dict(_DEFAULT_DATASETS)
        self._api_key = api_key
        self._model = model
        self._graphiti: Any = None
        self._ready = False

    # ── Dataset / group_id mapping ─────────────────────────────────

    def group_id(self, dataset: str) -> str:
        """Map a dataset name to a Graphiti group_id (identity mapping)."""
        return dataset

    def group_ids_for(self, visibility: str) -> list[str]:
        """Return group_ids visible at the given visibility level.

        Args:
            visibility: ``"master"`` returns all datasets.
                ``"all"`` returns only datasets whose DatasetConfig.visibility
                is ``"all"``.

        Returns:
            List of group_id strings.
        """
        configs = self._dataset_configs
        if not configs:
            configs = _DEFAULT_DATASETS

        if visibility == "master":
            return [self.group_id(name) for name in configs]

        return [self.group_id(name) for name, cfg in configs.items() if cfg.visibility == visibility]

    # ── Lifecycle ──────────────────────────────────────────────────

    @property
    def ready(self) -> bool:
        """Whether the backend has been started and is ready for use."""
        return self._ready

    async def start(self, api_key: str | None = None) -> None:
        """Initialize Graphiti with FalkorDB Lite driver and Anthropic LLM client.

        Args:
            api_key: Anthropic API key override. Falls back to constructor
                value, then env var / Keychain.
        """
        from graphiti_core import Graphiti
        from graphiti_core.llm_client.anthropic_client import AnthropicClient
        from graphiti_core.llm_client.config import LLMConfig

        from clarvis.vendor.falkor_lite import FalkorLiteDriver

        key = api_key or self._api_key or _get_api_key()
        if not key:
            raise RuntimeError("No Anthropic API key available for Graphiti backend")

        db_path = self._data_dir / "graphiti.falkor"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        driver = FalkorLiteDriver(path=str(db_path))
        # FalkorDriver.__init__ auto-schedules build_indices_and_constraints()
        # when an event loop is running, but we await it explicitly to ensure
        # indices are ready before returning.
        await driver.build_indices_and_constraints()

        llm_config = LLMConfig(api_key=key, model=self._model)
        llm_client = AnthropicClient(config=llm_config)

        self._graphiti = Graphiti(graph_driver=driver, llm_client=llm_client)
        self._ready = True
        logger.info("Graphiti backend started (db=%s)", db_path)

    async def close(self) -> None:
        """Shut down the Graphiti instance and reset state."""
        if self._graphiti is not None:
            try:
                await self._graphiti.close()
            except Exception:
                logger.exception("Error closing Graphiti")
            finally:
                self._graphiti = None
                self._ready = False
                logger.info("Graphiti backend closed")

    # ── Operations ─────────────────────────────────────────────────

    async def add_episode(
        self,
        text: str,
        *,
        dataset: str,
        name: str = "auto",
        source: str = "clarvis",
    ) -> None:
        """Ingest an episode into the knowledge graph.

        Args:
            text: The episode text content.
            dataset: Target dataset name (mapped to group_id).
            name: Episode name (default ``"auto"``).
            source: Source identifier (default ``"clarvis"``).
        """
        if not self._ready or self._graphiti is None:
            raise RuntimeError("Graphiti backend not started")

        from datetime import datetime, timezone

        await self._graphiti.add_episode(
            name=name,
            episode_body=text,
            source_description=f"clarvis/{dataset}",
            reference_time=datetime.now(timezone.utc),
            group_id=self.group_id(dataset),
        )

    async def search(
        self,
        query: str,
        *,
        group_ids: list[str] | None = None,
        num_results: int = 10,
    ) -> list[dict[str, Any]]:
        """Search the knowledge graph for relevant facts.

        Args:
            query: Natural language search query.
            group_ids: Restrict search to these group_ids. Defaults to all.
            num_results: Maximum number of results to return.

        Returns:
            List of dicts with keys: fact, source, created_at, valid_at,
            invalid_at.
        """
        if not self._ready or self._graphiti is None:
            raise RuntimeError("Graphiti backend not started")

        results = await self._graphiti.search(
            query=query,
            group_ids=group_ids or [],
            num_results=num_results,
        )

        return [
            {
                "fact": edge.fact,
                "source": edge.source,
                "created_at": edge.created_at,
                "valid_at": edge.valid_at,
                "invalid_at": edge.invalid_at,
            }
            for edge in results
        ]
