"""Widget configuration with clean, readable structure."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from ..core.colors import (
    DEFAULT_THEME,
    get_available_themes,
    load_theme,
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
        return cls(
            base=d.get("base", DEFAULT_THEME),
            overrides=d.get("overrides", {}),
        )


@dataclass
class DisplayConfig:
    """Display settings for the widget window."""

    # Grid size — single source of truth for both Python renderer and Swift widget.
    # Swift auto-derives window size from grid dims × measured font metrics.
    grid_width: int = 29
    grid_height: int = 12

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
class WakeWordConfig:
    """Configuration for wake word detection."""

    enabled: bool = False
    threshold: float = 0.3  # Wake word detection threshold
    vad_threshold: float = 0.2  # Voice activity detection threshold
    cooldown: float = 2.0  # Seconds between detections
    input_device: Optional[int] = None  # Audio input device index
    use_int8: bool = False  # Use INT8 quantized models

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        d = {
            "enabled": self.enabled,
            "threshold": self.threshold,
            "vad_threshold": self.vad_threshold,
            "cooldown": self.cooldown,
            "use_int8": self.use_int8,
        }
        if self.input_device is not None:
            d["input_device"] = self.input_device
        return d

    @staticmethod
    def from_dict(d: dict) -> "WakeWordConfig":
        """Deserialize from dictionary."""
        if not isinstance(d, dict):
            return WakeWordConfig()

        return WakeWordConfig(
            enabled=d.get("enabled", False),
            threshold=d.get("threshold", 0.3),
            vad_threshold=d.get("vad_threshold", 0.2),
            cooldown=d.get("cooldown", 2.0),
            input_device=d.get("input_device"),
            use_int8=d.get("use_int8", False),
        )


@dataclass
class VoiceConfig:
    """Configuration for voice command pipeline."""

    enabled: bool = True
    asr_timeout: float = 10.0
    asr_language: str = "en-US"
    silence_timeout: float = 3.0
    tts_voice: str = "Samantha"
    tts_enabled: bool = True
    tts_speed: float = 150
    text_linger: float = 3.0
    model: Optional[str] = None  # Claude model alias (e.g. "sonnet", "haiku", "opus")
    max_thinking_tokens: Optional[int] = None  # None = SDK default
    idle_timeout: float = 3600.0  # seconds before voice agent disconnects

    def to_dict(self) -> dict:
        d = {
            "enabled": self.enabled,
            "asr_timeout": self.asr_timeout,
            "asr_language": self.asr_language,
            "silence_timeout": self.silence_timeout,
            "tts_voice": self.tts_voice,
            "tts_enabled": self.tts_enabled,
            "tts_speed": self.tts_speed,
            "text_linger": self.text_linger,
        }
        if self.model is not None:
            d["model"] = self.model
        if self.max_thinking_tokens is not None:
            d["max_thinking_tokens"] = self.max_thinking_tokens
        d["idle_timeout"] = self.idle_timeout
        return d

    @staticmethod
    def from_dict(d: dict) -> "VoiceConfig":
        if not isinstance(d, dict):
            return VoiceConfig()
        return VoiceConfig(
            enabled=d.get("enabled", True),
            asr_timeout=d.get("asr_timeout", 10.0),
            asr_language=d.get("asr_language", "en-US"),
            silence_timeout=d.get("silence_timeout", 3.0),
            tts_voice=d.get("tts_voice", "Samantha"),
            tts_enabled=d.get("tts_enabled", True),
            tts_speed=d.get("tts_speed", 150),
            text_linger=d.get("text_linger", 3.0),
            model=d.get("model"),
            max_thinking_tokens=d.get("max_thinking_tokens"),
            idle_timeout=d.get("idle_timeout", 3600.0),
        )


@dataclass
class WidgetConfig:
    """Main configuration combining all sections."""

    theme: ThemeConfig
    display: DisplayConfig
    testing: TestingConfig
    token_usage: TokenUsageConfig = field(default_factory=TokenUsageConfig)
    wake_word: WakeWordConfig = field(default_factory=WakeWordConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)

    def to_dict(self) -> dict:
        return {
            "theme": self.theme.to_dict(),
            "display": asdict(self.display),
            "testing": asdict(self.testing),
            "token_usage": self.token_usage.to_dict(),
            "wake_word": self.wake_word.to_dict(),
            "voice": self.voice.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WidgetConfig":
        # Handle theme
        theme_data = d.get("theme", {})
        theme = ThemeConfig.from_dict(theme_data)

        # Validate and load theme
        if theme.base not in get_available_themes():
            theme.base = DEFAULT_THEME
        load_theme(theme.base, theme.overrides)

        # Handle display
        display_dict = d.get("display", {})
        display_known = {f.name for f in DisplayConfig.__dataclass_fields__.values()}
        display = DisplayConfig(**{k: v for k, v in display_dict.items() if k in display_known})

        # Handle testing
        testing_dict = d.get("testing", {})
        testing_known = {f.name for f in TestingConfig.__dataclass_fields__.values()}
        testing = TestingConfig(**{k: v for k, v in testing_dict.items() if k in testing_known})

        # Handle token_usage
        token_usage_dict = d.get("token_usage", {})
        token_usage = TokenUsageConfig.from_dict(token_usage_dict)

        # Handle wake_word
        wake_word_dict = d.get("wake_word", {})
        wake_word = WakeWordConfig.from_dict(wake_word_dict)

        # Handle voice
        voice_dict = d.get("voice", {})
        voice = VoiceConfig.from_dict(voice_dict)

        return cls(
            theme=theme,
            display=display,
            testing=testing,
            token_usage=token_usage,
            wake_word=wake_word,
            voice=voice,
        )

    def save(self, path: Path = CONFIG_PATH):
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.to_dict(), indent=2))
        temp.rename(path)

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "WidgetConfig":
        try:
            if path.exists():
                raw_data = json.loads(path.read_text())
                return cls.from_dict(raw_data)
        except (json.JSONDecodeError, IOError):
            pass
        return cls(
            theme=ThemeConfig(),
            display=DisplayConfig(),
            testing=TestingConfig(),
        )


# Global instance
_config: Optional[WidgetConfig] = None


def get_config() -> WidgetConfig:
    """Get current config."""
    global _config
    if _config is None:
        _config = WidgetConfig.load()
    return _config
