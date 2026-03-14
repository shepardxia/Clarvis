"""Knowledge graph (Cognee) command handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import CommandHandlers


def knowledge(
    self: CommandHandlers, *, query: str, search_type: str = "graph_completion", datasets: str | None = None, **kw
) -> str | dict:
    """Search the knowledge graph."""
    ds_list = [s.strip() for s in datasets.split(",")] if datasets else None
    return self._mem_op(lambda s: s.kg_search(query, search_type=search_type, datasets=ds_list, format=True))


def ingest(
    self: CommandHandlers, *, content_or_path: str, dataset: str = "knowledge", tags: str | None = None, **kw
) -> str | dict:
    """Ingest text or a file into the knowledge graph."""
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    return self._mem_op(lambda s: s.kg_ingest(content_or_path, dataset=dataset, tags=tag_list, format=True))


def entities(self: CommandHandlers, *, type_name: str | None = None, name: str | None = None, **kw) -> str | dict:
    """List entities in the knowledge graph."""
    return self._mem_op(lambda s: s.kg_list_entities(type_name=type_name, name=name, format=True))


def relations(
    self: CommandHandlers, *, entity_id: str | None = None, relationship_type: str | None = None, **kw
) -> str | dict:
    """List relationships between entities."""
    return self._mem_op(
        lambda s: s.kg_list_relations(entity_id=entity_id, relationship_type=relationship_type, format=True)
    )


def update_entity(self: CommandHandlers, *, entity_id: str, fields: dict, **kw) -> str | dict:
    """Update fields on a knowledge graph entity."""
    return self._mem_op(lambda s: s.kg_update_entity(entity_id, fields, format=True))


def merge_entities(self: CommandHandlers, *, entity_ids: list[str], **kw) -> str | dict:
    """Merge multiple entities into one."""
    return self._mem_op(lambda s: s.kg_merge_entities(entity_ids, format=True))


def delete_entity(self: CommandHandlers, *, node_id: str, **kw) -> str | dict:
    """Delete a node from the knowledge graph."""
    return self._mem_op(lambda s: s.kg_delete_entity(node_id, format=True))


def build_communities(self: CommandHandlers, **kw) -> str | dict:
    """Build community summaries from the knowledge graph."""
    return self._mem_op(lambda s: s.kg_build_communities(format=True))


COMMANDS: list[str] = [
    "knowledge",
    "ingest",
    "entities",
    "relations",
    "update_entity",
    "merge_entities",
    "delete_entity",
    "build_communities",
]
