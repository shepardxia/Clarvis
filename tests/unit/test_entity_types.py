"""Tests for Cognee DataPoint entity type definitions."""

from cognee.infrastructure.engine.models.DataPoint import DataPoint

from clarvis.agent.memory.entity_types import (
    ENTITY_TYPES,
    Band,
    Concept,
    Document,
    Event,
    Genre,
    Organization,
    Person,
    Project,
)

# Types that carry extra domain fields beyond name + description.
_FIELDED_TYPES = [Person, Organization, Project, Event, Document]

# Classification-only types: just name + description.
_CLASSIFICATION_TYPES = [Band, Concept, Genre]


# ── Registry completeness ────────────────────────────────────────


def test_registry_has_8_entries():
    assert len(ENTITY_TYPES) == 8


def test_registry_maps_class_names():
    for name, cls in ENTITY_TYPES.items():
        assert cls.__name__ == name


def test_all_types_are_datapoints():
    for name, cls in ENTITY_TYPES.items():
        assert issubclass(cls, DataPoint), f"{name} is not a DataPoint subclass"


# ── Index fields ──────────────────────────────────────────────────


def test_all_types_have_index_fields_on_name():
    for name, cls in ENTITY_TYPES.items():
        default_meta = cls.model_fields["metadata"].default
        assert "index_fields" in default_meta, f"{name} missing index_fields"
        assert "name" in default_meta["index_fields"], f"{name} index_fields missing 'name'"


def test_embeddable_data_returns_name():
    """DataPoint.get_embeddable_data should extract the name field."""
    p = Person(name="Alice")
    assert Person.get_embeddable_data(p) == "Alice"

    b = Band(name=" Mdou Moctar ")
    assert Band.get_embeddable_data(b) == "Mdou Moctar"  # strips whitespace


# ── Fielded types have their domain fields ────────────────────────


def test_person_has_roles_and_aliases():
    p = Person(name="Bob", roles=["engineer"], aliases=["Bobby"])
    assert p.roles == ["engineer"]
    assert p.aliases == ["Bobby"]


def test_organization_has_kind():
    o = Organization(name="MIT", kind="university")
    assert o.kind == "university"


def test_project_has_status():
    p = Project(name="Clarvis", status="active")
    assert p.status == "active"


def test_event_has_date_and_location():
    e = Event(name="Concert", date="2026-03-01", location="Brooklyn Steel")
    assert e.date == "2026-03-01"
    assert e.location == "Brooklyn Steel"


def test_document_has_source_url_and_doc_type():
    d = Document(name="Paper", source_url="https://arxiv.org/123", doc_type="paper")
    assert d.source_url == "https://arxiv.org/123"
    assert d.doc_type == "paper"


# ── Classification-only types have no extra fields ─────────────────


def test_classification_types_have_no_extra_fields():
    """Band, Concept, Genre should only add name + description to DataPoint."""
    base_fields = set(DataPoint.model_fields.keys())
    allowed_extra = {"name", "description"}

    for cls in _CLASSIFICATION_TYPES:
        own_fields = set(cls.model_fields.keys()) - base_fields
        unexpected = own_fields - allowed_extra
        assert not unexpected, f"{cls.__name__} has unexpected fields: {unexpected}"


# ── Instantiation and type field ──────────────────────────────────


def test_type_field_set_to_class_name():
    """DataPoint.__init__ sets type to the class name."""
    for name, cls in ENTITY_TYPES.items():
        instance = cls(name="test")
        assert instance.type == name


def test_all_types_have_description_field():
    """Every entity type should have an optional description field."""
    for name, cls in ENTITY_TYPES.items():
        assert "description" in cls.model_fields, f"{name} missing description"
        instance = cls(name="test")
        assert instance.description is None  # default is None


def test_all_types_have_id():
    """DataPoint provides a UUID id field."""
    for _, cls in ENTITY_TYPES.items():
        instance = cls(name="test")
        assert instance.id is not None
