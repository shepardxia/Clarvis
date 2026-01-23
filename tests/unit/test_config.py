"""Tests for widget configuration module."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from central_hub.widget.config import (
    ThemeConfig,
    DisplayConfig,
    TestingConfig,
    TokenUsageConfig,
    WidgetConfig,
    CONFIG_PATH,
)
from central_hub.core.colors import DEFAULT_THEME, get_available_themes


class TestThemeConfig:
    """Tests for ThemeConfig dataclass."""

    def test_default_values(self):
        """Should have sensible defaults."""
        config = ThemeConfig()
        assert config.base == DEFAULT_THEME
        assert config.overrides == {}

    def test_to_dict(self):
        """Should serialize to dict."""
        config = ThemeConfig(base="synthwave", overrides={"idle": [1.0, 0.0, 0.0]})
        d = config.to_dict()
        assert d["base"] == "synthwave"
        assert d["overrides"] == {"idle": [1.0, 0.0, 0.0]}

    def test_to_dict_omits_empty_overrides(self):
        """Should not include empty overrides in output."""
        config = ThemeConfig(base="modern")
        d = config.to_dict()
        assert "overrides" not in d

    def test_from_dict_full(self):
        """Should parse full config dict."""
        d = {"base": "matrix", "overrides": {"thinking": [0.5, 0.5, 0.5]}}
        config = ThemeConfig.from_dict(d)
        assert config.base == "matrix"
        assert config.overrides == {"thinking": [0.5, 0.5, 0.5]}

    def test_from_dict_legacy_string(self):
        """Should handle legacy string format (theme name only)."""
        config = ThemeConfig.from_dict("c64")
        assert config.base == "c64"
        assert config.overrides == {}

    def test_from_dict_minimal(self):
        """Should use defaults for missing keys."""
        config = ThemeConfig.from_dict({})
        assert config.base == DEFAULT_THEME
        assert config.overrides == {}


class TestDisplayConfig:
    """Tests for DisplayConfig dataclass."""

    def test_default_values(self):
        """Should have sensible defaults."""
        config = DisplayConfig()
        assert config.grid_width == 29
        assert config.grid_height == 12
        assert config.window_width == 280
        assert config.fps == 5
        assert 0.0 <= config.bg_alpha <= 1.0

    def test_all_fields_numeric(self):
        """All fields should be numeric types."""
        config = DisplayConfig()
        for field_name in config.__dataclass_fields__:
            val = getattr(config, field_name)
            assert isinstance(val, (int, float)), f"{field_name} should be numeric"


class TestTestingConfig:
    """Tests for TestingConfig dataclass."""

    def test_default_values(self):
        """Should have testing disabled by default."""
        config = TestingConfig()
        assert config.enabled is False
        assert config.status == "idle"
        assert config.weather == "clear"
        assert config.paused is False

    def test_custom_values(self):
        """Should accept custom values."""
        config = TestingConfig(
            enabled=True,
            status="thinking",
            weather="rain",
            context_percent=75.0
        )
        assert config.enabled is True
        assert config.status == "thinking"
        assert config.weather == "rain"
        assert config.context_percent == 75.0


class TestTokenUsageConfig:
    """Tests for TokenUsageConfig dataclass."""

    def test_default_values(self):
        """Should have sensible defaults."""
        config = TokenUsageConfig()
        assert config.enabled is True
        assert config.poll_interval == 120

    def test_custom_values(self):
        """Should accept custom values."""
        config = TokenUsageConfig(enabled=False, poll_interval=60)
        assert config.enabled is False
        assert config.poll_interval == 60

    def test_to_dict(self):
        """Should serialize to dictionary."""
        config = TokenUsageConfig(poll_interval=60)
        d = config.to_dict()
        assert d["enabled"] is True
        assert d["poll_interval"] == 60

    def test_from_dict(self):
        """Should deserialize from dictionary."""
        config = TokenUsageConfig.from_dict({"enabled": False, "poll_interval": 30})
        assert config.enabled is False
        assert config.poll_interval == 30

    def test_from_dict_with_defaults(self):
        """Should use defaults for missing fields."""
        config = TokenUsageConfig.from_dict({})
        assert config.enabled is True
        assert config.poll_interval == 120

    def test_from_dict_invalid_input(self):
        """Should return defaults for invalid input."""
        config = TokenUsageConfig.from_dict("invalid")
        assert config.enabled is True
        assert config.poll_interval == 120


class TestWidgetConfig:
    """Tests for WidgetConfig dataclass."""

    def test_to_dict_structure(self):
        """Should serialize to expected structure."""
        config = WidgetConfig(
            theme=ThemeConfig(),
            display=DisplayConfig(),
            testing=TestingConfig(),
        )
        d = config.to_dict()

        assert "theme" in d
        assert "display" in d
        assert "testing" in d
        assert "token_usage" in d

    def test_from_dict_new_format(self):
        """Should parse new format config."""
        d = {
            "theme": {"base": "synthwave"},
            "display": {"grid_width": 30, "fps": 10},
            "testing": {"enabled": True, "status": "running"},
            "token_usage": {"enabled": False, "poll_interval": 60},
        }

        config = WidgetConfig.from_dict(d)

        assert config.theme.base == "synthwave"
        assert config.display.grid_width == 30
        assert config.display.fps == 10
        assert config.testing.enabled is True
        assert config.testing.status == "running"
        assert config.token_usage.enabled is False
        assert config.token_usage.poll_interval == 60

    def test_from_dict_token_usage_defaults(self):
        """Should use defaults when token_usage section is missing."""
        d = {
            "theme": {"base": "modern"},
            "display": {},
            "testing": {},
        }

        config = WidgetConfig.from_dict(d)

        assert config.token_usage.enabled is True
        assert config.token_usage.poll_interval == 120

    def test_from_dict_legacy_static_key(self):
        """Should handle legacy 'static' key for display settings."""
        d = {
            "theme": {"base": "modern"},
            "static": {"grid_width": 25, "window_width": 300},
        }

        config = WidgetConfig.from_dict(d)

        assert config.display.grid_width == 25
        assert config.display.window_width == 300

    def test_from_dict_legacy_state_key(self):
        """Should handle legacy 'state' key for testing settings."""
        d = {
            "theme": {"base": "modern"},
            "state": {
                "testing": True,
                "test_status": "thinking",
                "test_weather": "snow",
                "test_context_percent": 80.0,
                "paused": True,
            },
        }

        config = WidgetConfig.from_dict(d)

        assert config.testing.enabled is True
        assert config.testing.status == "thinking"
        assert config.testing.weather == "snow"
        assert config.testing.context_percent == 80.0
        assert config.testing.paused is True

    def test_from_dict_invalid_theme_fallback(self):
        """Should fall back to default theme for invalid theme name."""
        d = {"theme": {"base": "nonexistent_theme"}}

        config = WidgetConfig.from_dict(d)

        assert config.theme.base == DEFAULT_THEME

    def test_from_dict_filters_unknown_display_keys(self):
        """Should ignore unknown keys in display section."""
        d = {
            "theme": {"base": "modern"},
            "display": {
                "grid_width": 30,
                "unknown_key": "should_be_ignored",
            },
        }

        config = WidgetConfig.from_dict(d)

        assert config.display.grid_width == 30
        assert not hasattr(config.display, "unknown_key")

    def test_roundtrip(self):
        """to_dict and from_dict should be inverse operations."""
        original = WidgetConfig(
            theme=ThemeConfig(base="matrix", overrides={"idle": [0.1, 0.2, 0.3]}),
            display=DisplayConfig(grid_width=35, fps=8),
            testing=TestingConfig(enabled=True, status="awaiting"),
        )

        d = original.to_dict()
        restored = WidgetConfig.from_dict(d)

        assert restored.theme.base == original.theme.base
        assert restored.theme.overrides == original.theme.overrides
        assert restored.display.grid_width == original.display.grid_width
        assert restored.display.fps == original.display.fps
        assert restored.testing.enabled == original.testing.enabled
        assert restored.testing.status == original.testing.status

    def test_get_colors_for_swift(self):
        """Should return merged colors for Swift widget."""
        config = WidgetConfig(
            theme=ThemeConfig(base="modern", overrides={"idle": [0.5, 0.5, 0.5]}),
            display=DisplayConfig(),
            testing=TestingConfig(),
        )

        colors = config.get_colors_for_swift()

        assert isinstance(colors, dict)
        assert colors["idle"] == [0.5, 0.5, 0.5]  # Override applied
        assert "thinking" in colors  # Other statuses present

    # Convenience property tests
    def test_grid_width_property(self):
        """Should expose display.grid_width."""
        config = WidgetConfig(
            theme=ThemeConfig(),
            display=DisplayConfig(grid_width=40),
            testing=TestingConfig(),
        )
        assert config.grid_width == 40

    def test_grid_height_property(self):
        """Should expose display.grid_height."""
        config = WidgetConfig(
            theme=ThemeConfig(),
            display=DisplayConfig(grid_height=15),
            testing=TestingConfig(),
        )
        assert config.grid_height == 15

    def test_test_status_property(self):
        """Should expose testing.status."""
        config = WidgetConfig(
            theme=ThemeConfig(),
            display=DisplayConfig(),
            testing=TestingConfig(status="running"),
        )
        assert config.test_status == "running"

    def test_testing_enabled_property(self):
        """Should expose testing.enabled."""
        config = WidgetConfig(
            theme=ThemeConfig(),
            display=DisplayConfig(),
            testing=TestingConfig(enabled=True),
        )
        assert config.testing_enabled is True


class TestWidgetConfigFileOps:
    """Tests for WidgetConfig file operations."""

    def test_save_creates_file(self, tmp_path):
        """Should create config file."""
        config_file = tmp_path / "config.json"
        config = WidgetConfig(
            theme=ThemeConfig(),
            display=DisplayConfig(),
            testing=TestingConfig(),
        )

        config.save(config_file)

        assert config_file.exists()
        data = json.loads(config_file.read_text())
        assert "theme" in data
        assert "display" in data
        assert "testing" in data

    def test_load_existing_file(self, tmp_path):
        """Should load config from existing file."""
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "theme": {"base": "synthwave"},
            "display": {"fps": 15},
            "testing": {"enabled": True},
        }))

        config = WidgetConfig.load(config_file)

        assert config.theme.base == "synthwave"
        assert config.display.fps == 15
        assert config.testing.enabled is True

    def test_load_missing_file_returns_defaults(self, tmp_path):
        """Should return default config when file doesn't exist."""
        config_file = tmp_path / "nonexistent.json"

        config = WidgetConfig.load(config_file)

        assert config.theme.base == DEFAULT_THEME
        assert config.testing.enabled is False

    def test_load_invalid_json_returns_defaults(self, tmp_path):
        """Should return default config for invalid JSON."""
        config_file = tmp_path / "config.json"
        config_file.write_text("not valid json {{{")

        config = WidgetConfig.load(config_file)

        assert config.theme.base == DEFAULT_THEME

    def test_save_atomic(self, tmp_path):
        """Save should be atomic (use temp file + rename)."""
        config_file = tmp_path / "config.json"
        config = WidgetConfig(
            theme=ThemeConfig(),
            display=DisplayConfig(),
            testing=TestingConfig(),
        )

        config.save(config_file)

        # No temp file should remain
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0
