"""Tests for MemUBackend initialization and dataset visibility scoping."""

from clarvis.services.memory.memu_backend import MemUBackend
from clarvis.widget.config import DatasetConfig

# ── Defaults ───────────────────────────────────────────────────────


def test_default_datasets():
    """Constructor defaults to parletre + agora datasets."""
    backend = MemUBackend(data_dir="/tmp/test-memu")
    assert backend._datasets == ["parletre", "agora"]


def test_custom_datasets():
    """Constructor accepts custom dataset list."""
    backend = MemUBackend(data_dir="/tmp/test-memu", datasets=["alpha", "beta", "gamma"])
    assert backend._datasets == ["alpha", "beta", "gamma"]


def test_not_ready_before_start():
    """Backend should not be ready before start() is called."""
    backend = MemUBackend(data_dir="/tmp/test-memu")
    assert backend.ready is False


# ── Visibility scoping ─────────────────────────────────────────────


def test_master_sees_all_datasets():
    """Master visibility returns every dataset regardless of config."""
    configs = {
        "parletre": DatasetConfig(visibility="master"),
        "agora": DatasetConfig(visibility="all"),
    }
    backend = MemUBackend(
        data_dir="/tmp/test-memu",
        datasets=["parletre", "agora"],
        dataset_configs=configs,
    )
    assert backend.visible_datasets("master") == ["parletre", "agora"]


def test_all_visibility_filters_master_only():
    """\x27all\x27 visibility excludes datasets marked as master-only."""
    configs = {
        "parletre": DatasetConfig(visibility="master"),
        "agora": DatasetConfig(visibility="all"),
    }
    backend = MemUBackend(
        data_dir="/tmp/test-memu",
        datasets=["parletre", "agora"],
        dataset_configs=configs,
    )
    result = backend.visible_datasets("all")
    assert result == ["agora"]


def test_all_visibility_with_all_datasets_visible():
    """If all datasets are visibility=\x27all\x27, \x27all\x27 returns them all."""
    configs = {
        "parletre": DatasetConfig(visibility="all"),
        "agora": DatasetConfig(visibility="all"),
    }
    backend = MemUBackend(
        data_dir="/tmp/test-memu",
        datasets=["parletre", "agora"],
        dataset_configs=configs,
    )
    result = backend.visible_datasets("all")
    assert result == ["parletre", "agora"]


def test_visibility_default_agora_is_all():
    """\x27agora\x27 defaults to visibility=\x27all\x27 when no config is provided."""
    backend = MemUBackend(
        data_dir="/tmp/test-memu",
        datasets=["parletre", "agora"],
        dataset_configs={},
    )
    result = backend.visible_datasets("all")
    assert result == ["agora"]


def test_visibility_default_unknown_is_master():
    """Unknown datasets default to visibility=\x27master\x27 when no config."""
    backend = MemUBackend(
        data_dir="/tmp/test-memu",
        datasets=["private_stuff", "agora"],
        dataset_configs={},
    )
    result = backend.visible_datasets("all")
    assert result == ["agora"]


def test_visibility_preserves_order():
    """visible_datasets preserves the original dataset order."""
    configs = {
        "alpha": DatasetConfig(visibility="all"),
        "beta": DatasetConfig(visibility="all"),
        "gamma": DatasetConfig(visibility="all"),
    }
    backend = MemUBackend(
        data_dir="/tmp/test-memu",
        datasets=["gamma", "alpha", "beta"],
        dataset_configs=configs,
    )
    assert backend.visible_datasets("all") == ["gamma", "alpha", "beta"]
    assert backend.visible_datasets("master") == ["gamma", "alpha", "beta"]


def test_visibility_empty_list_gets_defaults():
    """Empty dataset list is falsy — constructor falls back to defaults."""
    backend = MemUBackend(data_dir="/tmp/test-memu", datasets=[])
    # [] is falsy in Python, so `datasets or [defaults]` kicks in
    assert backend._datasets == ["parletre", "agora"]


def test_visibility_single_master_dataset():
    """Single master-only dataset: master sees it, all does not."""
    configs = {"private": DatasetConfig(visibility="master")}
    backend = MemUBackend(
        data_dir="/tmp/test-memu",
        datasets=["private"],
        dataset_configs=configs,
    )
    assert backend.visible_datasets("master") == ["private"]
    assert backend.visible_datasets("all") == []


def test_visibility_mixed_configs():
    """Mix of explicit configs and defaults works correctly."""
    configs = {
        "notes": DatasetConfig(visibility="all"),
        # "agora" has no explicit config — defaults to "all"
        # "secrets" has no explicit config — defaults to "master"
    }
    backend = MemUBackend(
        data_dir="/tmp/test-memu",
        datasets=["notes", "agora", "secrets"],
        dataset_configs=configs,
    )
    assert backend.visible_datasets("master") == ["notes", "agora", "secrets"]
    assert backend.visible_datasets("all") == ["notes", "agora"]
