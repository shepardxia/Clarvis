"""Widget configuration - static settings and runtime state in nested structure."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Callable

# Project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.json"


@dataclass
class StaticConfig:
    """Static settings (worth tracking in git)."""
    # Grid size (Python renderer)
    grid_width: int = 29
    grid_height: int = 12

    # Window size (Swift widget display)
    window_width: int = 280
    window_height: int = 220
    corner_radius: int = 24
    bg_alpha: float = 0.75
    font_size: int = 14
    border_width: int = 2
    pulse_speed: float = 0.1

    # Avatar position offsets (relative to auto-centered position)
    avatar_x_offset: int = 0
    avatar_y_offset: int = 0

    # Bar position offsets (relative to auto-centered position)
    bar_x_offset: int = 0
    bar_y_offset: int = 0

    # Animation
    fps: int = 5


@dataclass
class StateConfig:
    """Runtime state (for testing)."""
    testing: bool = False
    test_status: str = "idle"
    test_weather: str = "clear"
    test_weather_intensity: float = 0.5
    test_wind_speed: float = 5.0  # mph, affects snow drift
    test_context_percent: float = 50.0
    paused: bool = False


@dataclass
class WidgetConfig:
    """Combined config with static and state sections."""
    static: StaticConfig
    state: StateConfig

    def to_dict(self) -> dict:
        return {
            "static": asdict(self.static),
            "state": asdict(self.state),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WidgetConfig":
        static_dict = d.get("static", {})
        state_dict = d.get("state", {})

        # Filter to known fields
        static_known = {f.name for f in StaticConfig.__dataclass_fields__.values()}
        state_known = {f.name for f in StateConfig.__dataclass_fields__.values()}

        static = StaticConfig(**{k: v for k, v in static_dict.items() if k in static_known})
        state = StateConfig(**{k: v for k, v in state_dict.items() if k in state_known})

        return cls(static=static, state=state)

    def save(self, path: Path = CONFIG_PATH):
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.to_dict(), indent=2))
        temp.rename(path)

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "WidgetConfig":
        try:
            if path.exists():
                return cls.from_dict(json.loads(path.read_text()))
        except (json.JSONDecodeError, IOError):
            pass
        return cls(static=StaticConfig(), state=StateConfig())

    # Convenience accessors for backward compatibility
    @property
    def grid_width(self) -> int:
        return self.static.grid_width

    @property
    def grid_height(self) -> int:
        return self.static.grid_height

    @property
    def testing(self) -> bool:
        return self.state.testing

    @property
    def test_status(self) -> str:
        return self.state.test_status

    @property
    def test_weather(self) -> str:
        return self.state.test_weather

    @property
    def test_weather_intensity(self) -> float:
        return self.state.test_weather_intensity

    @property
    def test_context_percent(self) -> float:
        return self.state.test_context_percent


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
    subprocess.run(["pkill", "-f", "central_hub"], capture_output=True)
    subprocess.run(["pkill", "-f", "ClarvisWidget"], capture_output=True)

    time.sleep(0.5)

    subprocess.Popen(
        [sys.executable, "-m", "central_hub.daemon"],
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
