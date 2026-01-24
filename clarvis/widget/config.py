"""Widget configuration with clean, readable structure."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Callable

from ..core.colors import (
    load_theme,
    get_available_themes,
    get_merged_theme_colors,
    DEFAULT_THEME,
)

# Project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.json"


@dataclass
class ThemeConfig:
    """Theme settings with optional color overrides."""
    base: str = DEFAULT_THEME
    overrides: dict[str, list[float]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {"base": self.base}
        if self.overrides:
            d["overrides"] = self.overrides
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ThemeConfig":
        if isinstance(d, str):
            # Legacy: "theme": "c64" -> ThemeConfig(base="c64")
            return cls(base=d)
        return cls(
            base=d.get("base", DEFAULT_THEME),
            overrides=d.get("overrides", {}),
        )


@dataclass
class DisplayConfig:
    """Display settings for the widget window."""
    # Grid size (Python renderer)
    grid_width: int = 29
    grid_height: int = 12

    # Window size (Swift widget)
    window_width: int = 280
    window_height: int = 220
    corner_radius: int = 24
    bg_alpha: float = 0.75
    font_size: int = 14
    border_width: int = 2
    pulse_speed: float = 0.1

    # Position offsets
    avatar_x_offset: int = 0
    avatar_y_offset: int = 0
    bar_x_offset: int = 0
    bar_y_offset: int = 0

    # Animation
    fps: int = 5


@dataclass
class TestingConfig:
    """Testing mode settings for development."""
    enabled: bool = False
    status: str = "idle"
    weather: str = "clear"
    weather_intensity: float = 0.5
    wind_speed: float = 5.0
    context_percent: float = 50.0
    paused: bool = False


@dataclass
class TokenUsageConfig:
    """Configuration for token usage tracking."""
    enabled: bool = True
    poll_interval: int = 120  # seconds

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "enabled": self.enabled,
            "poll_interval": self.poll_interval,
        }

    @staticmethod
    def from_dict(d: dict) -> "TokenUsageConfig":
        """Deserialize from dictionary."""
        if not isinstance(d, dict):
            return TokenUsageConfig()

        return TokenUsageConfig(
            enabled=d.get("enabled", True),
            poll_interval=d.get("poll_interval", 120),
        )


@dataclass
class WidgetConfig:
    """Main configuration combining all sections."""
    theme: ThemeConfig
    display: DisplayConfig
    testing: TestingConfig
    token_usage: TokenUsageConfig = field(default_factory=TokenUsageConfig)

    def to_dict(self) -> dict:
        return {
            "theme": self.theme.to_dict(),
            "display": asdict(self.display),
            "testing": asdict(self.testing),
            "token_usage": self.token_usage.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WidgetConfig":
        # Handle theme (supports legacy "theme": "name" format)
        theme_data = d.get("theme", DEFAULT_THEME)
        theme = ThemeConfig.from_dict(theme_data)

        # Validate and load theme
        if theme.base not in get_available_themes():
            theme.base = DEFAULT_THEME
        load_theme(theme.base, theme.overrides)

        # Handle display (supports legacy "static" key)
        display_dict = d.get("display", d.get("static", {}))
        display_known = {f.name for f in DisplayConfig.__dataclass_fields__.values()}
        display = DisplayConfig(**{k: v for k, v in display_dict.items() if k in display_known})

        # Handle testing (supports legacy "state" key with test_ prefix)
        testing_dict = d.get("testing", {})
        if not testing_dict and "state" in d:
            # Convert legacy state format
            state = d["state"]
            testing_dict = {
                "enabled": state.get("testing", False),
                "status": state.get("test_status", "idle"),
                "weather": state.get("test_weather", "clear"),
                "weather_intensity": state.get("test_weather_intensity", 0.5),
                "wind_speed": state.get("test_wind_speed", 5.0),
                "context_percent": state.get("test_context_percent", 50.0),
                "paused": state.get("paused", False),
            }
        testing_known = {f.name for f in TestingConfig.__dataclass_fields__.values()}
        testing = TestingConfig(**{k: v for k, v in testing_dict.items() if k in testing_known})

        # Handle token_usage
        token_usage_dict = d.get("token_usage", {})
        token_usage = TokenUsageConfig.from_dict(token_usage_dict)

        return cls(theme=theme, display=display, testing=testing, token_usage=token_usage)

    def save(self, path: Path = CONFIG_PATH):
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.to_dict(), indent=2))
        temp.rename(path)

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "WidgetConfig":
        try:
            if path.exists():
                raw_data = json.loads(path.read_text())
                config = cls.from_dict(raw_data)
                # Migrate legacy format to new format
                if "static" in raw_data or "state" in raw_data or isinstance(raw_data.get("theme"), str):
                    config.save(path)
                return config
        except (json.JSONDecodeError, IOError):
            pass
        return cls(
            theme=ThemeConfig(),
            display=DisplayConfig(),
            testing=TestingConfig(),
        )

    def get_colors_for_swift(self) -> dict[str, list[float]]:
        """Get merged theme colors as RGB arrays for Swift widget."""
        return get_merged_theme_colors(self.theme.base, self.theme.overrides)

    # Convenience accessors for backward compatibility
    @property
    def grid_width(self) -> int:
        return self.display.grid_width

    @property
    def grid_height(self) -> int:
        return self.display.grid_height

    @property
    def test_status(self) -> str:
        return self.testing.status

    @property
    def test_weather(self) -> str:
        return self.testing.weather

    @property
    def test_weather_intensity(self) -> float:
        return self.testing.weather_intensity

    @property
    def test_context_percent(self) -> float:
        return self.testing.context_percent

    @property
    def test_wind_speed(self) -> float:
        return self.testing.wind_speed

    # Legacy property name for testing.enabled
    @property
    def testing_enabled(self) -> bool:
        return self.testing.enabled


class ConfigWatcher:
    """Watches config file for changes."""

    def __init__(self, callback: Callable[[WidgetConfig], None], poll_interval: float = 0.2):
        self.callback = callback
        self.poll_interval = poll_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_mtime = 0.0
        self._last_config: Optional[WidgetConfig] = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _watch_loop(self):
        while self._running:
            try:
                if CONFIG_PATH.exists():
                    mtime = CONFIG_PATH.stat().st_mtime
                    if mtime != self._last_mtime:
                        self._last_mtime = mtime
                        config = WidgetConfig.load()
                        if self._last_config is None or config.to_dict() != self._last_config.to_dict():
                            self._last_config = config
                            self.callback(config)
            except (IOError, OSError):
                pass
            time.sleep(self.poll_interval)


# Global instance
_config: Optional[WidgetConfig] = None
_watchers: list[ConfigWatcher] = []


def get_config() -> WidgetConfig:
    """Get current config."""
    global _config
    if _config is None:
        _config = WidgetConfig.load()
    return _config


def set_config(config: WidgetConfig):
    """Set and save config."""
    global _config
    _config = config
    config.save()


def watch_config(callback: Callable[[WidgetConfig], None]) -> ConfigWatcher:
    """Start watching config for changes."""
    watcher = ConfigWatcher(callback)
    watcher.start()
    _watchers.append(watcher)
    return watcher


def restart_daemon_and_widget():
    """Restart the daemon process and widget."""
    subprocess.run(["pkill", "-f", "clarvis"], capture_output=True)
    subprocess.run(["pkill", "-f", "ClarvisWidget"], capture_output=True)

    time.sleep(0.5)

    subprocess.Popen(
        [sys.executable, "-m", "clarvis.daemon"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    widget_path = PROJECT_ROOT / "ClarvisWidget" / "ClarvisWidget"
    if widget_path.exists():
        subprocess.Popen(
            [str(widget_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
