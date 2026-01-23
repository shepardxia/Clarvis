"""Widget configuration - shared state between debug UI and daemon."""

import json
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Callable

CONFIG_PATH = Path("/tmp/widget-config.json")

@dataclass
class WidgetConfig:
    """Widget rendering configuration."""
    # Grid
    grid_width: int = 29
    grid_height: int = 12

    # Avatar position offsets
    avatar_x_offset: int = 0
    avatar_y_offset: int = 0
    bar_y_offset: int = 1

    # Weather (auto = read from hub data)
    weather_type: str = "auto"
    weather_intensity: float = 0.6

    # Animation
    fps: int = 5
    paused: bool = False

    # Status override (None = use hook events)
    status_override: Optional[str] = None
    context_percent_override: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "WidgetConfig":
        # Filter to only known fields
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)

    def save(self, path: Path = CONFIG_PATH):
        """Save config to file."""
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.to_dict(), indent=2))
        temp.rename(path)

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "WidgetConfig":
        """Load config from file, or return defaults."""
        try:
            if path.exists():
                return cls.from_dict(json.loads(path.read_text()))
        except (json.JSONDecodeError, IOError):
            pass
        return cls()


class ConfigWatcher:
    """Watches config file for changes and calls callback."""

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


# Global config instance
_config: Optional[WidgetConfig] = None
_watchers: list[ConfigWatcher] = []


def get_config() -> WidgetConfig:
    """Get current config (loads from file if needed)."""
    global _config
    if _config is None:
        _config = WidgetConfig.load()
    return _config


def set_config(config: WidgetConfig):
    """Set and save config."""
    global _config
    _config = config
    config.save()


def update_config(**kwargs):
    """Update specific config fields and save."""
    config = get_config()
    for key, value in kwargs.items():
        if hasattr(config, key):
            setattr(config, key, value)
    set_config(config)


def watch_config(callback: Callable[[WidgetConfig], None]) -> ConfigWatcher:
    """Start watching config for changes."""
    watcher = ConfigWatcher(callback)
    watcher.start()
    _watchers.append(watcher)
    return watcher
