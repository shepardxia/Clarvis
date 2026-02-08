"""Cognee-based memory service for Clarvis.

Wraps cognee's async API to provide knowledge graph memory:
add text -> cognify (build graph) -> search (query graph).

Graceful degradation: all methods return error dicts instead of raising,
so the daemon never crashes if cognee is unavailable or misconfigured.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CogneeMemoryService:
    """Manages cognee lifecycle and provides add/cognify/search operations.

    All public methods check ``_ready`` before proceeding and return an
    error dict if the service has not been started or failed to initialize.
    """

    _ready: bool = False

    def __init__(self) -> None:
        self._ready = False

    # ------------------------------------------------------------------
    # Credential helpers
    # ------------------------------------------------------------------

    KEYCHAIN_SERVICE = "Claude Code-credentials"

    @staticmethod
    def _get_api_key() -> Optional[str]:
        """Retrieve Anthropic API key: env var first, then macOS Keychain.

        Returns:
            API key string or None if unavailable.
        """
        # 1. Environment variable
        key = os.environ.get("ANTHROPIC_API_KEY")
        if key:
            return key

        # 2. macOS Keychain (same pattern as token_usage.py)
        try:
            result = subprocess.run(
                [
                    "security",
                    "find-generic-password",
                    "-s",
                    CogneeMemoryService.KEYCHAIN_SERVICE,
                    "-w",
                ],
                capture_output=True,
                text=False,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout.decode())
                return data.get("claudeAiOauth", {}).get("accessToken")
        except Exception as exc:
            logger.debug("Keychain lookup failed: %s", exc)

        return None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, config: dict) -> None:
        """Configure cognee and run migrations.

        Args:
            config: The ``memory`` section from config.json.
        """
        import cognee

        # Resolve data directory
        data_dir = config.get("data_dir", "~/.clarvis/memory")
        data_path = Path(data_dir).expanduser()
        data_path.mkdir(parents=True, exist_ok=True)

        # Set environment for cognee before configure()
        api_key = self._get_api_key()
        if api_key:
            os.environ.setdefault("LLM_API_KEY", api_key)
        else:
            logger.warning("No Anthropic API key found; cognee may not work")

        os.environ.setdefault("DATA_ROOT_DIRECTORY", str(data_path))

        # Configure cognee for Anthropic LLM
        cognee.config.set_llm_config(
            {
                "llm_provider": "anthropic",
                "llm_model": "claude-haiku-4-5-20251001",
                "llm_api_key": api_key or "",
            }
        )

        # Configure local embeddings (fastembed — no API key needed)
        from cognee.infrastructure.databases.vector.embeddings.config import (
            get_embedding_config,
        )

        emb_config = get_embedding_config()
        emb_config.embedding_provider = "fastembed"
        emb_config.embedding_model = "BAAI/bge-small-en-v1.5"
        emb_config.embedding_dimensions = 384

        # Disable multi-user access control for local use
        os.environ.setdefault("ENABLE_BACKEND_ACCESS_CONTROL", "false")

        # Initialize storage (creates SQLite tables, vector store, etc.)
        await cognee.prune.prune_system(metadata=True)

        self._ready = True

    async def _safe_start(self, config: dict) -> None:
        """Wrapper that catches exceptions so the daemon never crashes."""
        try:
            await self.start(config)
            logger.info("Memory service ready")
        except Exception:
            logger.exception("Memory service failed to start")

    async def stop(self) -> None:
        """Shut down the memory service."""
        self._ready = False
        logger.info("Memory service stopped")

    # ------------------------------------------------------------------
    # Guard
    # ------------------------------------------------------------------

    def _check_ready(self) -> Optional[Dict[str, Any]]:
        """Return an error dict if service is not ready, else None."""
        if not self._ready:
            return {"error": "Memory service not available"}
        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def add(self, data: str, dataset: str = "clarvis") -> Dict[str, Any]:
        """Add text data to a cognee dataset.

        Args:
            data: Text content to store.
            dataset: Dataset name (default ``"clarvis"``).

        Returns:
            Status dict with ``status`` key on success, ``error`` on failure.
        """
        err = self._check_ready()
        if err:
            return err
        try:
            import cognee

            await cognee.add(data, dataset)
            return {"status": "ok", "dataset": dataset, "bytes": len(data)}
        except Exception as exc:
            logger.exception("cognee.add failed")
            return {"error": str(exc)}

    async def cognify(self, dataset: str = "clarvis") -> Dict[str, Any]:
        """Build/update the knowledge graph for a dataset.

        Args:
            dataset: Dataset name (default ``"clarvis"``).

        Returns:
            Status dict with ``status`` key on success, ``error`` on failure.
        """
        err = self._check_ready()
        if err:
            return err
        try:
            import cognee

            await cognee.cognify(dataset)
            return {"status": "ok", "dataset": dataset}
        except Exception as exc:
            logger.exception("cognee.cognify failed")
            return {"error": str(exc)}

    async def search(
        self,
        query: str,
        search_type: str = "GRAPH_COMPLETION",
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search the knowledge graph.

        Args:
            query: Natural language query.
            search_type: Cognee search type (default ``"GRAPH_COMPLETION"``).
            top_k: Maximum results to return.

        Returns:
            List of result dicts on success, or a single-element list
            containing an error dict on failure.
        """
        err = self._check_ready()
        if err:
            return [err]
        try:
            import cognee
            from cognee.api.v1.search import SearchType

            st = SearchType[search_type]
            results = await cognee.search(query_text=query, query_type=st, top_k=top_k)
            # Normalize results to list of dicts
            normalized: List[Dict[str, Any]] = []
            for item in results:
                if isinstance(item, dict):
                    normalized.append(item)
                else:
                    normalized.append({"result": str(item)})
            return normalized
        except Exception as exc:
            logger.exception("cognee.search failed")
            return [{"error": str(exc)}]

    async def status(self) -> Dict[str, Any]:
        """Return service status information.

        Returns:
            Dict with ``ready`` flag and optional details.
        """
        info: Dict[str, Any] = {"ready": self._ready}
        if self._ready:
            try:
                import cognee

                info["cognee_version"] = getattr(cognee, "__version__", "unknown")
            except Exception:
                pass
        return info
