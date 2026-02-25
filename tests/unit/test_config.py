"""Tests for widget config schema quality and constraints."""

import pytest

from clarvis.display.config import (
    DatasetConfig,
    DisplayConfig,
    MemoryConfig,
    MusicConfig,
    PiConfig,
    TestingConfig,
    ThemeConfig,
    VoiceConfig,
    WakeupConfig,
    WakeWordConfig,
    WidgetConfig,
)


@pytest.mark.parametrize(
    "model",
    [
        ThemeConfig,
        DisplayConfig,
        TestingConfig,
        MusicConfig,
        DatasetConfig,
        MemoryConfig,
        WakeWordConfig,
        VoiceConfig,
        PiConfig,
        WakeupConfig,
        WidgetConfig,
    ],
)
def test_all_fields_have_descriptions(model):
    """Every field should have a description for self-documenting schema."""
    schema = model.model_json_schema()
    for name, prop in schema.get("properties", {}).items():
        assert "description" in prop, f"{model.__name__}.{name} missing description"


def test_round_trip():
    """Config should survive serialization round-trips."""
    cfg = WidgetConfig(
        voice=VoiceConfig(tts_voice="Alex", wake_word=WakeWordConfig(threshold=0.9)),
        music=MusicConfig(max_volume=60),
    )
    cfg2 = WidgetConfig.model_validate(cfg.model_dump())
    assert cfg.model_dump() == cfg2.model_dump()


def test_volume_out_of_range():
    """MusicConfig.max_volume should reject values outside 0-100."""
    with pytest.raises(Exception):
        MusicConfig(max_volume=101)
    with pytest.raises(Exception):
        MusicConfig(max_volume=-1)


def test_memory_config_datasets():
    """Memory config has bank visibility mapping via hindsight.banks."""
    cfg = MemoryConfig()
    assert "parletre" in cfg.hindsight.banks
    assert "agora" in cfg.hindsight.banks
    assert cfg.hindsight.banks["parletre"].visibility == "master"
    assert cfg.hindsight.banks["agora"].visibility == "all"
    assert cfg.auto_ingest is True
    assert cfg.staleness_hours == 24


def test_memory_config_no_old_fields():
    """Old cognee-specific fields should be gone."""
    cfg = MemoryConfig()
    assert not hasattr(cfg, "rate_limit_rpm")
    assert not hasattr(cfg, "data_per_batch")
    assert not hasattr(cfg, "default_dataset")
