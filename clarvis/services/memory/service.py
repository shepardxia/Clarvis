"""Unified dual memory service — Graphiti + memU."""

import logging
from pathlib import Path
from typing import Any

from clarvis.services.memory.graphiti_backend import GraphitiBackend
from clarvis.services.memory.memu_backend import MemUBackend
from clarvis.widget.config import DatasetConfig

logger = logging.getLogger(__name__)


class DualMemoryService:
    """Orchestrates both memory backends behind a unified interface.

    memU handles categorization and context assembly. Graphiti handles
    structured knowledge queries (temporal, relational, traversal).
    """

    def __init__(
        self,
        *,
        data_dir: Path | str,
        dataset_configs: dict[str, DatasetConfig] | None = None,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-6",
    ) -> None:
        self.data_dir = Path(data_dir).expanduser()
        self._dataset_configs = dataset_configs or {}
        self._api_key = api_key
        self._model = model

        datasets = list(self._dataset_configs.keys()) or ["parletre", "agora"]

        self._memu = MemUBackend(
            data_dir=self.data_dir / "memu",
            datasets=datasets,
            dataset_configs=self._dataset_configs,
            api_key=api_key,
            model=model,
        )
        self._graphiti = GraphitiBackend(
            data_dir=self.data_dir / "graphiti",
            dataset_configs=self._dataset_configs,
            api_key=api_key,
            model=model,
        )
        self._ready = False

    # ── Lifecycle ───────────────────────────────────────────────────

    async def start(self) -> None:
        """Start both backends and wire GraphitiStep if both are ready."""
        await self._memu.start(api_key=self._api_key)
        await self._graphiti.start(api_key=self._api_key)
        if self._memu.ready and self._graphiti.ready:
            self._memu.register_graphiti_step(self._graphiti)
        self._ready = True
        logger.info("DualMemoryService started")

    async def stop(self) -> None:
        """Shut down backends."""
        await self._graphiti.close()
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    # ── Unified operations ──────────────────────────────────────────

    async def search(self, query: str, *, visibility: str = "master", top_k: int = 10) -> list[dict[str, Any]]:
        """Search both backends, merge results."""
        datasets = self._memu.visible_datasets(visibility=visibility)
        group_ids = self._graphiti.group_ids_for(visibility=visibility)

        results: list[dict[str, Any]] = []
        if self._memu.ready:
            memu_results = await self._memu.search(query, datasets=datasets, top_k=top_k)
            results.extend(memu_results)
        if self._graphiti.ready:
            graphiti_results = await self._graphiti.search(query, group_ids=group_ids, num_results=top_k)
            results.extend(graphiti_results)
        return results

    async def add(self, content: str, *, dataset: str, memory_type: str = "knowledge") -> dict[str, Any]:
        """Add to both backends."""
        backends: dict[str, Any] = {}
        if self._memu.ready:
            backends["memu"] = await self._memu.add(content, dataset=dataset, memory_type=memory_type)
        if self._graphiti.ready:
            await self._graphiti.add_episode(content, dataset=dataset)
            backends["graphiti"] = {"status": "ok"}
        return {"status": "ok", "dataset": dataset, "backends": backends}

    async def forget(self, item_id: str, *, dataset: str) -> dict[str, Any]:
        """Remove from memU. Graphiti nodes removed via graph tools separately."""
        if self._memu.ready:
            return await self._memu.forget(item_id, dataset=dataset)
        return {"error": "memU not ready"}

    # ── Context assembly ────────────────────────────────────────────

    async def recall(
        self,
        query: str,
        *,
        visibility: str = "master",
        context_messages: list[dict[str, str]] | None = None,
        method: str = "rag",
    ) -> dict[str, Any]:
        """Recall memory using memU's tiered retrieval, supplemented by Graphiti.

        Returns a structured dict with ``categories``, ``items``, ``resources``,
        ``next_step_query`` from memU, plus ``graphiti_facts`` from Graphiti.
        """
        datasets = self._memu.visible_datasets(visibility=visibility)
        result: dict[str, Any] = {}

        if self._memu.ready and datasets:
            result = await self._memu.recall(
                query,
                context_messages=context_messages,
                datasets=datasets,
                method=method,
            )

        # Supplement with Graphiti facts
        if self._graphiti.ready:
            group_ids = self._graphiti.group_ids_for(visibility=visibility)
            try:
                graphiti_facts = await self._graphiti.search(
                    query,
                    group_ids=group_ids,
                    num_results=10,
                )
                result["graphiti_facts"] = graphiti_facts
            except Exception:
                logger.exception("Graphiti recall failed; continuing without")
                result.setdefault("graphiti_facts", [])
        else:
            result.setdefault("graphiti_facts", [])

        return result

    # ── Ingestion pipeline ──────────────────────────────────────────

    async def ingest_transcript(self, text: str, *, dataset: str) -> dict[str, Any]:
        """Ingest raw transcript through memU's extraction pipeline.

        memU handles noisy raw text well (categorization, summarization).
        If GraphitiStep is registered in the pipeline, Graphiti receives
        pre-extracted items automatically — no separate add_episode() call.
        """
        backends: dict[str, Any] = {}
        if self._memu.ready:
            backends["memu"] = await self._memu.memorize(text, dataset=dataset)
        return {"status": "ok", "dataset": dataset, "backends": backends}
