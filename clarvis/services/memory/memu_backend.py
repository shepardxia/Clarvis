"""memU backend — categorized memory with extraction pipeline."""

import logging
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default dataset visibility: "agora" is visible to all, everything else is master-only.
_DEFAULT_VISIBILITY: dict[str, str] = {"agora": "all"}


class MemUBackend:
    """Thin wrapper around ``memu.MemoryService`` with dataset scoping.

    Datasets are logical partitions stored via ``user_data={"dataset": name}``.
    Each dataset has a visibility level (``"master"`` or ``"all"``) that
    controls which MCP ports / agents can access it.
    """

    def __init__(
        self,
        data_dir: Path,
        datasets: list[str] | None = None,
        dataset_configs: dict[str, Any] | None = None,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-6",
    ) -> None:
        self._data_dir = Path(data_dir).expanduser()
        self._datasets = datasets or ["parletre", "agora"]
        self._dataset_configs = dataset_configs or {}
        self._api_key = api_key
        self._model = model
        self._svc: Any | None = None  # memu.MemoryService once started

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def ready(self) -> bool:
        """True once the memU service has been initialized."""
        return self._svc is not None

    # ------------------------------------------------------------------
    # Visibility scoping
    # ------------------------------------------------------------------

    def visible_datasets(self, visibility: str) -> list[str]:
        """Return dataset names visible at the given access level.

        Args:
            visibility: ``"master"`` returns all datasets.
                        ``"all"`` returns only datasets whose config
                        visibility is ``"all"``.

        If a dataset has no explicit ``DatasetConfig``, the default is
        ``"all"`` for ``"agora"`` and ``"master"`` for everything else.
        """
        if visibility == "master":
            return list(self._datasets)

        result: list[str] = []
        for ds in self._datasets:
            cfg = self._dataset_configs.get(ds)
            if cfg is not None:
                ds_vis = cfg.visibility
            else:
                ds_vis = _DEFAULT_VISIBILITY.get(ds, "master")
            if ds_vis == "all":
                result.append(ds)
        return result

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, api_key: str | None = None) -> None:
        """Initialize the memU MemoryService with vendored patches.

        Applies two vendor patches (SQLite column mapping + Claude LLM backend)
        then creates a MemoryService backed by SQLite for persistence.

        Args:
            api_key: Anthropic API key.  Falls back to the key passed at
                     construction time.
        """
        key = api_key or self._api_key
        if not key:
            logger.warning("No API key provided; memU backend will not start")
            return

        from clarvis.vendor.memu_claude import apply_patch as apply_claude_patch
        from clarvis.vendor.memu_sqlite import apply_patch as apply_sqlite_patch

        apply_sqlite_patch()
        apply_claude_patch()

        from memu.app.service import MemoryService

        self._data_dir.mkdir(parents=True, exist_ok=True)

        db_path = self._data_dir / "memu.db"

        llm_profiles = {
            "default": {
                "client_backend": "claude_sdk",
                "api_key": key,
                "chat_model": self._model,
            },
            "embedding": {
                "provider": "openai",
                "api_key": key,
                "embed_model": "text-embedding-3-small",
            },
        }

        self._svc = MemoryService(
            database_config={
                "metadata_store": {
                    "provider": "sqlite",
                    "url": f"sqlite:///{db_path}",
                },
            },
            llm_profiles=llm_profiles,
        )
        logger.info("memU backend ready (sqlite=%s, datasets=%s)", db_path, self._datasets)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def add(
        self,
        content: str,
        *,
        dataset: str,
        memory_type: str = "knowledge",
    ) -> dict[str, Any]:
        """Create a single memory item in *dataset*.

        Args:
            content: The text to memorize.
            dataset: Target dataset name.
            memory_type: One of memU's MemoryType values (default ``"knowledge"``).

        Returns:
            Status dict.
        """
        if not self.ready:
            return {"error": "memU backend not started"}
        try:
            await self._svc.create_memory_item(
                memory_type=memory_type,
                memory_content=content,
                memory_categories=[dataset],
            )
            return {"status": "ok", "dataset": dataset, "bytes": len(content)}
        except Exception as exc:
            logger.exception("memU add failed")
            return {"error": str(exc)}

    async def search(
        self,
        query: str,
        *,
        datasets: list[str],
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """Search memory items scoped to *datasets*.

        Args:
            query: Natural language query.
            datasets: Dataset names to search within.
            top_k: Max results.

        Returns:
            List of result dicts, or a single-element error list.
        """
        if not self.ready:
            return [{"error": "memU backend not started"}]
        try:
            if len(datasets) == 1:
                where = {"dataset": datasets[0]}
            else:
                where = {"dataset__in": datasets}

            result = await self._svc.retrieve(
                queries=[{"role": "user", "content": query}],
                where=where,
            )
            # retrieve() returns structured dict with categories/items/resources
            normalized: list[dict[str, Any]] = []
            for item in result.get("items", []):
                if isinstance(item, dict):
                    normalized.append(item)
                elif hasattr(item, "model_dump"):
                    normalized.append(item.model_dump())
                else:
                    normalized.append({"text": str(item)})
            return normalized[:top_k]
        except Exception as exc:
            logger.exception("memU search failed")
            return [{"error": str(exc)}]

    async def forget(
        self,
        item_id: str,
        *,
        dataset: str,
    ) -> dict[str, Any]:
        """Delete a memory item.

        Args:
            item_id: The item\'s identifier.
            dataset: Dataset the item belongs to.

        Returns:
            Status dict.
        """
        if not self.ready:
            return {"error": "memU backend not started"}
        try:
            self._svc.delete_memory_item(memory_id=item_id)
            return {"status": "ok", "deleted": item_id, "dataset": dataset}
        except Exception as exc:
            logger.exception("memU forget failed")
            return {"error": str(exc)}

    async def get_categories(
        self,
        *,
        datasets: list[str],
    ) -> list[dict[str, Any]]:
        """List category summaries filtered by *datasets*.

        Returns:
            List of category info dicts, or error list.
        """
        if not self.ready:
            return [{"error": "memU backend not started"}]
        try:
            if len(datasets) == 1:
                where = {"dataset": datasets[0]}
            else:
                where = {"dataset__in": datasets}

            result = await self._svc.list_memory_categories(where=where)
            # Returns {"categories": [list of category dicts]}
            return result.get("categories", [])
        except Exception as exc:
            logger.exception("memU get_categories failed")
            return [{"error": str(exc)}]

    async def memorize(
        self,
        text: str,
        *,
        dataset: str,
    ) -> dict[str, Any]:
        """Ingest raw text through memU's extraction pipeline.

        Writes *text* to a temp file and calls ``memorize()`` which runs
        memU's full extraction (chunking, entity extraction, categorization).

        Args:
            text: Raw text to ingest.
            dataset: Target dataset name.

        Returns:
            Status dict.
        """
        if not self.ready:
            return {"error": "memU backend not started"}
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".txt",
                delete=False,
                dir=str(self._data_dir),
            ) as f:
                f.write(text)
                tmp_path = f.name

            await self._svc.memorize(
                resource_url=tmp_path,
                modality="text",
                user={"dataset": dataset},
            )

            # Clean up temp file
            Path(tmp_path).unlink(missing_ok=True)

            return {"status": "ok", "dataset": dataset, "bytes": len(text)}
        except Exception as exc:
            logger.exception("memU memorize failed")
            # Try cleanup on failure too
            if tmp_path:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass
            return {"error": str(exc)}

    def register_graphiti_step(self, graphiti_backend: Any) -> None:
        """Insert GraphitiStep into the memorize pipeline after categorize_items."""
        if not self.ready:
            logger.warning("Cannot register GraphitiStep: memU backend not started")
            return
        from clarvis.services.memory.graphiti_step import make_graphiti_step

        step = make_graphiti_step(graphiti_backend)
        self._svc.insert_step_after(
            target_step_id="categorize_items",
            new_step=step,
            pipeline="memorize",
        )
        logger.info("GraphitiStep registered in memorize pipeline")

    async def recall(
        self,
        query: str,
        *,
        context_messages: list[dict[str, str]] | None = None,
        datasets: list[str],
        method: str = "rag",
    ) -> dict[str, Any]:
        """Full tiered retrieval with conversation context.

        Uses memU's ``retrieve()`` with context messages for better
        relevance, and returns the structured result directly.

        Args:
            query: The main recall query.
            context_messages: Prior conversation turns as
                ``[{"role": "user"|"assistant", "content": "..."}]``.
                These help memU understand conversational context.
            datasets: Dataset names to scope retrieval.
            method: ``"rag"`` (fast, default) or ``"llm"`` (deep reasoning).

        Returns:
            Structured dict with keys: ``categories``, ``items``,
            ``resources``, ``next_step_query``, etc.
        """
        if not self.ready:
            return {"error": "memU backend not started"}
        try:
            if len(datasets) == 1:
                where = {"dataset": datasets[0]}
            else:
                where = {"dataset__in": datasets}

            # Build query list: context messages first, main query last
            queries: list[dict[str, str]] = []
            if context_messages:
                queries.extend(context_messages)
            queries.append({"role": "user", "content": query})

            # Set retrieval method
            prev_method = self._svc.retrieve_config.method
            self._svc.retrieve_config.method = method
            try:
                result = await self._svc.retrieve(
                    queries=queries,
                    where=where,
                )
            finally:
                self._svc.retrieve_config.method = prev_method

            return result
        except Exception as exc:
            logger.exception("memU recall failed")
            return {"error": str(exc)}
