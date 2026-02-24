"""Tests for GraphitiBackend initialization and dataset scoping logic."""

import pytest

from clarvis.services.memory.graphiti_backend import _DEFAULT_DATASETS, GraphitiBackend
from clarvis.widget.config import DatasetConfig

# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def two_dataset_configs():
    """Standard two-dataset config matching Clarvis defaults."""
    return {
        "parletre": DatasetConfig(visibility="master"),
        "agora": DatasetConfig(visibility="all"),
    }


@pytest.fixture
def three_dataset_configs():
    """Three datasets with mixed visibility."""
    return {
        "private": DatasetConfig(visibility="master"),
        "shared": DatasetConfig(visibility="all"),
        "notes": DatasetConfig(visibility="all"),
    }


@pytest.fixture
def backend(tmp_path, two_dataset_configs):
    """A GraphitiBackend with default two-dataset config."""
    return GraphitiBackend(
        data_dir=tmp_path / "memory",
        dataset_configs=two_dataset_configs,
        api_key="test-key",
    )


# ── Constructor ───────────────────────────────────────────────────


def test_constructor_stores_data_dir(tmp_path):
    """data_dir is stored as a Path."""
    b = GraphitiBackend(data_dir=tmp_path / "mem", dataset_configs={})
    assert b._data_dir == tmp_path / "mem"


def test_constructor_defaults_datasets(tmp_path):
    """Omitting dataset_configs falls back to default datasets."""
    b = GraphitiBackend(data_dir=tmp_path)
    assert set(b._dataset_configs.keys()) == {"parletre", "agora"}


def test_constructor_accepts_api_key(tmp_path):
    """api_key passed to constructor is stored."""
    b = GraphitiBackend(data_dir=tmp_path, api_key="sk-test")
    assert b._api_key == "sk-test"


# ── ready property ────────────────────────────────────────────────


def test_not_ready_before_start(backend):
    """Backend should not be ready before start() is called."""
    assert backend.ready is False


# ── group_id (identity mapping) ──────────────────────────────────


def test_group_id_identity(backend):
    """group_id returns the dataset name unchanged."""
    assert backend.group_id("parletre") == "parletre"
    assert backend.group_id("agora") == "agora"
    assert backend.group_id("anything") == "anything"


# ── group_ids_for (visibility scoping) ────────────────────────────


def test_master_returns_all_datasets(backend):
    """'master' visibility returns all configured dataset names."""
    ids = backend.group_ids_for("master")
    assert set(ids) == {"parletre", "agora"}


def test_all_returns_only_all_visibility(backend):
    """'all' visibility returns only datasets with visibility='all'."""
    ids = backend.group_ids_for("all")
    assert ids == ["agora"]


def test_master_with_three_datasets(tmp_path, three_dataset_configs):
    """'master' returns all three datasets."""
    b = GraphitiBackend(
        data_dir=tmp_path,
        dataset_configs=three_dataset_configs,
    )
    ids = b.group_ids_for("master")
    assert set(ids) == {"private", "shared", "notes"}


def test_all_with_three_datasets(tmp_path, three_dataset_configs):
    """'all' returns only the two datasets with visibility='all'."""
    b = GraphitiBackend(
        data_dir=tmp_path,
        dataset_configs=three_dataset_configs,
    )
    ids = b.group_ids_for("all")
    assert set(ids) == {"shared", "notes"}


def test_master_visibility_empty_configs_uses_defaults(tmp_path):
    """When configs dict is empty, falls back to default datasets for master."""
    b = GraphitiBackend(data_dir=tmp_path, dataset_configs={})
    ids = b.group_ids_for("master")
    assert set(ids) == {"parletre", "agora"}


def test_all_visibility_empty_configs_uses_defaults(tmp_path):
    """When configs dict is empty, falls back to default datasets for all."""
    b = GraphitiBackend(data_dir=tmp_path, dataset_configs={})
    ids = b.group_ids_for("all")
    assert ids == ["agora"]


def test_unknown_visibility_returns_empty(backend):
    """An unrecognized visibility level returns an empty list."""
    ids = backend.group_ids_for("private")
    assert ids == []


# ── Default datasets constant ────────────────────────────────────


def test_default_datasets_match_config_defaults():
    """Module-level _DEFAULT_DATASETS should match MemoryConfig defaults."""
    assert "parletre" in _DEFAULT_DATASETS
    assert "agora" in _DEFAULT_DATASETS
    assert _DEFAULT_DATASETS["parletre"].visibility == "master"
    assert _DEFAULT_DATASETS["agora"].visibility == "all"
