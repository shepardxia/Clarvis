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
        self._start_config: Optional[dict] = None
        self._log_file: Optional[Path] = None

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
        self._start_config = config
        import cognee

        # Resolve data directory
        data_dir = config.get("data_dir", "~/.clarvis/memory")
        data_path = Path(data_dir).expanduser()
        data_path.mkdir(parents=True, exist_ok=True)
        self._log_file = data_path / "add_log.jsonl"

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

        # No explicit init needed — cognee creates tables on first add/cognify

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

    async def _check_ready(self) -> Optional[Dict[str, Any]]:
        """Return an error dict if service is not ready, else None.

        If the service failed to start but config is available, attempts
        a single re-initialization before giving up.
        """
        if self._ready:
            return None
        if not self._start_config:
            return {"error": "Memory service not available"}
        try:
            await self.start(self._start_config)
            logger.info("Memory service recovered")
            return None
        except Exception:
            logger.debug("Memory service recovery failed", exc_info=True)
            return {"error": "Memory service not available"}

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
        err = await self._check_ready()
        if err:
            return err
        try:
            from datetime import datetime, timezone

            import cognee

            await cognee.add(data, dataset)
            # Append to local audit log
            if self._log_file:
                try:
                    record = json.dumps(
                        {
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "dataset": dataset,
                            "data": data,
                        }
                    )
                    with open(self._log_file, "a", encoding="utf-8") as f:
                        f.write(record + "\n")
                except OSError:
                    pass  # Non-critical — don't fail the add
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
        err = await self._check_ready()
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
        datasets: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Search the knowledge graph.

        Args:
            query: Natural language query.
            search_type: Cognee search type (default ``"GRAPH_COMPLETION"``).
            top_k: Maximum results to return.
            datasets: Optional list of dataset names to scope the search.

        Returns:
            List of result dicts on success, or a single-element list
            containing an error dict on failure.
        """
        err = await self._check_ready()
        if err:
            return [err]
        try:
            import cognee
            from cognee.api.v1.search import SearchType

            st = SearchType[search_type]
            results = await cognee.search(
                query_text=query,
                query_type=st,
                top_k=top_k,
                datasets=datasets,
            )
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

    async def list_items(self, dataset: str) -> List[Dict[str, Any]]:
        """List all data items in a dataset with content preview.

        Returns a list of dicts with data_id, preview (first ~80 chars), created_at.
        """
        err = await self._check_ready()
        if err:
            return [err]
        try:
            from pathlib import Path

            import cognee

            ds_list = await cognee.datasets.list_datasets()
            target = next((ds for ds in ds_list if ds.name == dataset), None)
            if not target:
                return [{"error": f"Dataset '{dataset}' not found"}]

            items = await cognee.datasets.list_data(target.id)
            from cognee.infrastructure.files.storage import get_storage_config

            data_root = Path(get_storage_config()["data_root_directory"])

            result = []
            for item in items:
                preview = ""
                try:
                    loc = getattr(item, "raw_data_location", None)
                    if loc:
                        if loc.startswith("file://"):
                            from urllib.parse import urlparse

                            fp = Path(urlparse(loc).path)
                        else:
                            fp = Path(loc)
                            if not fp.is_absolute():
                                fp = data_root / loc
                        if fp.exists():
                            preview = fp.read_text(encoding="utf-8")[:80].replace("\n", " ").strip()
                except Exception:
                    pass

                result.append(
                    {
                        "data_id": str(item.id),
                        "preview": preview,
                        "created_at": item.created_at.isoformat() if item.created_at else None,
                    }
                )
            return result
        except Exception as exc:
            logger.exception("cognee list_items failed")
            return [{"error": str(exc)}]

    async def delete(self, data_id: str, dataset: str, mode: str = "soft") -> Dict[str, Any]:
        """Delete a data item from a dataset.

        Args:
            data_id: UUID string of the data item.
            dataset: Dataset name containing the item.
            mode: "soft" (default) or "hard" (also removes orphaned entities).
        """
        err = await self._check_ready()
        if err:
            return err
        try:
            from uuid import UUID

            import cognee

            ds_list = await cognee.datasets.list_datasets()
            target = next((ds for ds in ds_list if ds.name == dataset), None)
            if not target:
                return {"error": f"Dataset '{dataset}' not found"}

            result = await cognee.delete(UUID(data_id), target.id, mode=mode)
            return {"status": "ok", "deleted": data_id, "dataset": dataset, "details": str(result)}
        except Exception as exc:
            logger.exception("cognee.delete failed")
            return {"error": str(exc)}

    async def status(self) -> Dict[str, Any]:
        """Return service status and dataset index.

        Returns:
            Dict with ``ready`` flag, cognee version, and ``datasets`` list
            containing per-dataset metadata (name, item_count, total_tokens,
            timestamps).
        """
        info: Dict[str, Any] = {"ready": self._ready}
        if self._ready:
            try:
                import cognee

                info["cognee_version"] = getattr(cognee, "__version__", "unknown")
            except Exception:
                pass
            try:
                import cognee

                ds_list = await cognee.datasets.list_datasets()
                datasets = []
                for ds in ds_list:
                    items = await cognee.datasets.list_data(ds.id)
                    datasets.append(
                        {
                            "name": ds.name,
                            "item_count": len(items),
                            "total_bytes": sum(getattr(d, "data_size", 0) or 0 for d in items),
                            "total_tokens": sum(getattr(d, "token_count", 0) or 0 for d in items),
                            "created_at": ds.created_at.isoformat() if ds.created_at else None,
                            "updated_at": ds.updated_at.isoformat() if ds.updated_at else None,
                        }
                    )
                info["datasets"] = datasets
            except Exception as exc:
                logger.debug("Failed to list datasets: %s", exc)
                info["datasets"] = []
        return info

    # ------------------------------------------------------------------
    # Graph traversal
    # ------------------------------------------------------------------

    async def graph_traverse(self, entity: str, max_connections: int = 50) -> Dict[str, Any]:
        """Find entities by name and return their graph neighborhoods.

        Args:
            entity: Entity name to search for (substring match).
            max_connections: Cap on connections returned per entity.

        Returns:
            Dict with ``matches`` list, each containing ``node`` info and
            ``connections`` list.  Returns ``error`` on failure.
        """
        err = await self._check_ready()
        if err:
            return err
        try:
            from cognee.infrastructure.databases.graph import get_graph_engine

            engine = await get_graph_engine()

            matches = await engine.query(
                "MATCH (n:Node) WHERE n.name CONTAINS $name RETURN n.id, n.name, n.type LIMIT 5",
                {"name": entity},
            )

            if not matches:
                return {
                    "matches": [],
                    "hint": "No entities found. Use memory_graph_overview to list available entities.",
                }

            results = []
            for row in matches:
                node_id = str(row[0])
                node_info = {"id": node_id, "name": row[1], "type": row[2]}

                connections = await engine.get_connections(node_id)
                conn_list = []
                for src, rel, tgt in connections[:max_connections]:
                    conn_list.append(
                        {
                            "relationship": rel.get("relationship_name", "unknown"),
                            "target": {
                                "id": str(tgt.get("id", "")),
                                "name": tgt.get("name"),
                                "type": tgt.get("type"),
                            },
                        }
                    )

                results.append({"node": node_info, "connections": conn_list})

            return {"matches": results}
        except Exception as exc:
            logger.exception("graph_traverse failed")
            return {"error": str(exc)}

    async def graph_query(self, cypher: str, params: Optional[Dict[str, Any]] = None) -> List[Any]:
        """Execute a read-only Cypher query against the graph.

        Args:
            cypher: Kuzu-dialect Cypher query (read-only).
            params: Optional query parameters.

        Returns:
            List of result rows (each a list of values), or error list.
        """
        err = await self._check_ready()
        if err:
            return [err]

        upper = cypher.strip().upper()
        for keyword in ("CREATE", "DELETE", "SET ", "MERGE", "REMOVE", "DROP"):
            if keyword in upper:
                return [{"error": f"Write operations not allowed (found '{keyword}')."}]

        try:
            from cognee.infrastructure.databases.graph import get_graph_engine

            engine = await get_graph_engine()
            rows = await engine.query(cypher, params or {})

            def _ser(v: Any) -> Any:
                if isinstance(v, (str, int, float, bool, type(None))):
                    return v
                if isinstance(v, dict):
                    return {k: _ser(val) for k, val in v.items()}
                if isinstance(v, (list, tuple)):
                    return [_ser(i) for i in v]
                return str(v)

            return [_ser(list(row)) for row in rows]
        except Exception as exc:
            logger.exception("graph_query failed")
            return [{"error": str(exc)}]

    async def graph_overview(self) -> Dict[str, Any]:
        """Return graph metrics, entity names, and relationship types.

        Returns:
            Dict with ``node_count``, ``edge_count``, ``entities`` list,
            and ``relationship_types`` list.
        """
        err = await self._check_ready()
        if err:
            return err
        try:
            from collections import Counter

            from cognee.infrastructure.databases.graph import get_graph_engine

            engine = await get_graph_engine()

            node_rows = await engine.query("MATCH (n:Node) RETURN count(n)")
            edge_rows = await engine.query("MATCH ()-[r:EDGE]->() RETURN count(r)")
            node_count = node_rows[0][0] if node_rows else 0
            edge_count = edge_rows[0][0] if edge_rows else 0

            entity_rows = await engine.query("MATCH (n:Node) WHERE n.name IS NOT NULL RETURN n.name, n.type LIMIT 200")
            entities = [{"name": r[0], "type": r[1]} for r in entity_rows]

            # Aggregate in Python for Kuzu compatibility
            rel_rows = await engine.query("MATCH ()-[r:EDGE]->() RETURN r.relationship_name")
            rel_counts = Counter(r[0] for r in rel_rows)
            relationships = [{"type": t, "count": c} for t, c in rel_counts.most_common()]

            return {
                "node_count": node_count,
                "edge_count": edge_count,
                "entities": entities,
                "relationship_types": relationships,
            }
        except Exception as exc:
            logger.exception("graph_overview failed")
            return {"error": str(exc)}

    async def graph_delete_node(self, node_id: str) -> Dict[str, Any]:
        """Delete a node from the graph, vector store, and relationship ledger.

        Mirrors cognee's own deletion flow:
        1. DETACH DELETE in Kuzu (graph + edges)
        2. Remove embeddings from all vector collections
        3. Soft-delete ledger rows (``deleted_at`` timestamp)

        Args:
            node_id: UUID string of the node (from traverse/overview results).

        Returns:
            Dict with deleted node info on success, ``error`` on failure.
        """
        err = await self._check_ready()
        if err:
            return err
        try:
            from datetime import datetime, timezone
            from uuid import UUID

            from cognee.infrastructure.databases.graph import get_graph_engine
            from cognee.infrastructure.databases.relational import (
                get_relational_engine,
            )
            from cognee.infrastructure.databases.vector import get_vector_engine

            engine = await get_graph_engine()

            # Fetch node info before deleting
            rows = await engine.query(
                "MATCH (n:Node) WHERE n.id = $nid RETURN n.id, n.name, n.type",
                {"nid": node_id},
            )
            if not rows:
                return {"error": f"Node '{node_id}' not found."}

            name = rows[0][1]
            node_type = rows[0][2]

            # 1. Graph: DETACH DELETE removes node + all edges
            await engine.delete_node(node_id)

            # 2. Vector: remove embeddings from all collections
            try:
                vector_engine = get_vector_engine()
                node_uuid_str = str(node_id)
                for collection in [
                    "DocumentChunk_text",
                    "Entity_name",
                    "EntityType_name",
                    "EdgeType_relationship_name",
                    "TextDocument_name",
                    "TextSummary_text",
                ]:
                    if await vector_engine.has_collection(collection):
                        await vector_engine.delete_data_points(collection, [node_uuid_str])
            except Exception:
                logger.debug("Vector cleanup skipped: %s", node_id)

            # 3. Ledger: soft-delete relationship rows
            try:
                node_uuid = UUID(node_id.replace("-", ""))
                db_engine = get_relational_engine()
                async with db_engine.get_async_session() as session:
                    from cognee.modules.data.models.graph_relationship_ledger import (
                        GraphRelationshipLedger,
                    )
                    from sqlalchemy import or_, update

                    stmt = (
                        update(GraphRelationshipLedger)
                        .where(
                            or_(
                                GraphRelationshipLedger.source_node_id == node_uuid,
                                GraphRelationshipLedger.destination_node_id == node_uuid,
                            )
                        )
                        .values(deleted_at=datetime.now(timezone.utc))
                    )
                    await session.execute(stmt)
                    await session.commit()
            except Exception:
                logger.debug("Ledger cleanup skipped: %s", node_id)

            return {
                "status": "ok",
                "deleted": {"id": node_id, "name": name, "type": node_type},
            }
        except Exception as exc:
            logger.exception("graph_delete_node failed")
            return {"error": str(exc)}
