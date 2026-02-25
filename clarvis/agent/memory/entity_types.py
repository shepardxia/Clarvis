"""Cognee DataPoint entity types for knowledge graph ingestion.

Passed to ``cognee.cognify(graph_model=...)`` to guide entity classification
and attribute extraction.

Types with extra fields trigger an LLM call per entity to extract structured
attributes.  Classification-only types (name only) are free.

All types subclass cognee's ``DataPoint`` so they integrate natively with
cognee's pipeline, graph storage, and embedding infrastructure.
"""

from cognee.infrastructure.engine.models.DataPoint import DataPoint

# ── With fields ──────────────────────────────────────────────


class Person(DataPoint):
    """Someone with a name and identity. Humans, AI personas, characters."""

    name: str
    description: str | None = None
    roles: list[str] | None = None
    aliases: list[str] | None = None
    metadata: dict = {"index_fields": ["name"]}


class Organization(DataPoint):
    """A formal entity with members and structure — company, university,
    nonprofit, community branch, collective, or institution."""

    name: str
    description: str | None = None
    kind: str | None = None
    metadata: dict = {"index_fields": ["name"]}


class Project(DataPoint):
    """A named effort with participants and goals — software project,
    research project, initiative, campaign, or creative work."""

    name: str
    description: str | None = None
    status: str | None = None
    metadata: dict = {"index_fields": ["name"]}


class Event(DataPoint):
    """A time-bound occurrence — meeting, concert, trip, deadline,
    release, milestone, or activity."""

    name: str
    description: str | None = None
    date: str | None = None
    location: str | None = None
    metadata: dict = {"index_fields": ["name"]}


class Document(DataPoint):
    """A named piece of content — paper, article, Notion page,
    meeting transcript, report, album, or book."""

    name: str
    description: str | None = None
    source_url: str | None = None
    doc_type: str | None = None
    metadata: dict = {"index_fields": ["name"]}


# ── Classification-only (no extra fields beyond name) ────────


class Band(DataPoint):
    """A musical group, ensemble, or duo."""

    name: str
    description: str | None = None
    metadata: dict = {"index_fields": ["name"]}


class Concept(DataPoint):
    """An idea, theory, framework, technique, or intellectual topic.
    Named abstractions that connect concrete entities."""

    name: str
    description: str | None = None
    metadata: dict = {"index_fields": ["name"]}


class Genre(DataPoint):
    """A musical or artistic genre, scene, or movement."""

    name: str
    description: str | None = None
    metadata: dict = {"index_fields": ["name"]}


# ── Registry ─────────────────────────────────────────────────

ENTITY_TYPES: dict[str, type[DataPoint]] = {
    "Person": Person,
    "Band": Band,
    "Organization": Organization,
    "Project": Project,
    "Event": Event,
    "Concept": Concept,
    "Genre": Genre,
    "Document": Document,
}
