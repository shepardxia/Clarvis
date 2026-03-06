"""Widget configuration with clean, readable structure."""

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..core.persistence import json_load_safe
from .colors import (
    DEFAULT_THEME,
    get_available_themes,
    load_theme,
)

# Project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.json"


# ── Core (always needed) ───────────────────────────────────────────


class ThemeConfig(BaseModel):
    """Theme settings with optional color overrides."""

    base: str = Field(
        default=DEFAULT_THEME, description="Theme name (modern, synthwave, crt-amber, crt-green, c64, matrix)"
    )
    overrides: dict[str, list[float]] = Field(default_factory=dict, description="Per-status RGB color overrides")


class DisplayConfig(BaseModel):
    """Display settings for the widget window."""

    model_config = ConfigDict(extra="ignore")

    grid_width: int = Field(default=29, description="Character grid width (Swift derives window size from this)")
    grid_height: int = Field(default=12, description="Character grid height")
    corner_radius: int = Field(default=24, description="Window corner radius in points")
    bg_alpha: float = Field(default=0.75, description="Background opacity (0.0–1.0)")
    font_size: int = Field(default=14, description="Monospace font size in points")
    font_name: str = Field(default="Courier", description="Monospace font family name")
    border_width: int = Field(default=2, description="Window border width in points")
    pulse_speed: float = Field(default=0.1, description="Border pulse animation speed")
    avatar_x_offset: int = Field(default=0, description="Avatar horizontal offset in grid cells")
    avatar_y_offset: int = Field(default=0, description="Avatar vertical offset in grid cells")
    bar_x_offset: int = Field(default=0, description="Progress bar horizontal offset in grid cells")
    bar_y_offset: int = Field(default=0, description="Progress bar vertical offset in grid cells")
    mic_x_offset: int = Field(default=0, description="Mic icon horizontal offset in grid cells")
    mic_y_offset: int = Field(default=0, description="Mic icon vertical offset in grid cells")
    fps: int = Field(default=5, description="Target render frames per second")
    skin: str = Field(default="classic", description="Face skin tag for .cv palette/sequence selection")


class TestingConfig(BaseModel):
    """Testing mode settings for development."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=False, description="Enable testing mode (overrides real state)")
    status: str = Field(default="idle", description="Fixed status to display")
    weather: str = Field(default="clear", description="Fixed weather type")
    weather_intensity: float = Field(default=0.5, description="Weather particle intensity (0.0–1.0)")
    wind_speed: float = Field(default=5.0, description="Wind speed for weather particles")
    context_percent: float = Field(default=50.0, description="Fixed context window percentage")
    paused: bool = Field(default=False, description="Pause all animations")


# ── Music extra ────────────────────────────────────────────────────


class MusicConfig(BaseModel):
    """Configuration for music integration (Spotify)."""

    max_volume: int = Field(
        default=75, ge=0, le=100, description="Volume cap for absolute and relative changes (0–100)"
    )


# ── Memory extra ───────────────────────────────────────────────────


class DatasetConfig(BaseModel):
    """Per-dataset visibility and description."""

    visibility: Literal["master", "all"] = Field(
        default="all",
        description="Who can access this dataset: 'master' (Clarvis only) or 'all' (all agents).",
    )
    description: str = Field(
        default="",
        description="Human-readable description of the dataset's purpose. Shown to agents in MCP tool schemas.",
    )


class HindsightConfig(BaseModel):
    """Configuration for Hindsight conversational memory backend."""

    db_url: str = Field(
        default="pg0",
        description="Database URL for Hindsight MemoryEngine (e.g. 'pg0' or full postgres URL).",
    )
    banks: dict[str, DatasetConfig] = Field(
        default_factory=lambda: {
            "parletre": DatasetConfig(
                visibility="master",
                description=(
                    "The speaking-being (Lacan). Personal memory: Shepard's facts,"
                    " Clarvis's observations, research, music taste. Clarvis only."
                ),
            ),
            "agora": DatasetConfig(
                visibility="all",
                description="The public square. Shared knowledge visible to all agents.",
            ),
        },
        description="Bank definitions with visibility scoping.",
    )


class CogneeConfig(BaseModel):
    """Configuration for Cognee document knowledge graph backend."""

    db_host: str = Field(default="localhost", description="PostgreSQL host.")
    db_port: int = Field(default=5432, description="PostgreSQL port.")
    db_name: str = Field(default="clarvis_knowledge", description="PostgreSQL database name for Cognee.")
    db_username: str | None = Field(default=None, description="PostgreSQL username (None = $USER).")
    db_password: str = Field(default="", description="PostgreSQL password.")
    graph_path: str | None = Field(
        default=None,
        description="Path for kuzu embedded graph database (None = ~/.clarvis/memory/knowledge_graph_kuzu).",
    )
    llm_provider: str = Field(default="anthropic", description="LLM provider for entity extraction.")
    llm_model: str = Field(default="claude-sonnet-4-6", description="LLM model for entity extraction.")
    llm_api_key: str | None = Field(default=None, description="LLM API key (None = from env).")


class DocumentsConfig(BaseModel):
    """Configuration for the document watcher service."""

    watch_dir: str = Field(
        default="~/.clarvis/documents",
        description="Directory to watch for new/changed files to ingest via Cognee.",
    )
    poll_interval: int = Field(default=60, ge=5, description="Seconds between directory scans.")
    hash_store_path: str = Field(
        default="~/.clarvis/memory/doc_hashes.json",
        description="Path to persist content-hash state for dedup.",
    )


class MemoryConfig(BaseModel):
    """Configuration for the entire memory system.

    Maintenance pipeline (retain + reflect) settings are top-level.
    Backend configs (hindsight, cognee, documents) are nested since
    they each have many backend-specific fields.
    """

    enabled: bool = Field(default=False, description="Enable memory system (Hindsight + Cognee)")
    data_dir: str = Field(default="~/.clarvis/memory", description="Root directory for memory storage")

    # Reflect: consolidate facts into observations + refresh mental models
    reflect_fact_threshold: int = Field(
        default=50,
        ge=1,
        description="Minimum unconsolidated facts before reflection triggers.",
    )
    reflect_staleness_hours: int = Field(
        default=24,
        ge=1,
        description="Hours since last reflection before a fallback reflect triggers (even below fact threshold).",
    )

    # Backend configs
    hindsight: HindsightConfig = Field(
        default_factory=HindsightConfig,
        description="Hindsight conversational memory backend settings.",
    )
    cognee: CogneeConfig = Field(
        default_factory=CogneeConfig,
        description="Cognee document knowledge graph backend settings.",
    )
    documents: DocumentsConfig = Field(
        default_factory=DocumentsConfig,
        description="Document watcher settings.",
    )


# ── Voice extra ────────────────────────────────────────────────────


class WakeWordConfig(BaseModel):
    """Configuration for wake word detection."""

    enabled: bool = Field(default=False, description="Enable wake word listener")
    model: str | None = Field(default=None, description="Model stem name, e.g. 'r5_ebf' → models/r5_ebf.onnx")
    model_path: str | None = Field(default=None, description="Explicit absolute path to .onnx model (overrides stem)")
    threshold: float = Field(default=0.3, description="Detection confidence threshold (0.0–1.0)")
    vad_threshold: float = Field(default=0.2, description="Voice activity detection threshold")
    patience: int = Field(default=4, description="Consecutive above-threshold frames required")
    sample_rate: int = Field(default=48000, description="Audio capture rate (decimated to 16kHz for inference)")
    input_device: int | None = Field(default=None, description="PyAudio input device index (None = system default)")
    capture_dir: str | None = Field(
        default=None, description="Dir to save audio clips on wake trigger (for false-positive review)"
    )
    capture_seconds: float = Field(default=5.0, description="Seconds of audio to keep in capture ring buffer")

    @model_validator(mode="after")
    def _resolve_model_path(self) -> "WakeWordConfig":
        """Resolve model stem → absolute path if model_path not explicitly set."""
        if self.model_path is None and self.model is not None:
            candidate = PROJECT_ROOT / "models" / f"{self.model}.onnx"
            if candidate.exists():
                self.model_path = str(candidate)
        return self


class VoiceConfig(BaseModel):
    """Configuration for voice I/O pipeline (TTS, ASR, wake word)."""

    enabled: bool = Field(default=True, description="Enable voice pipeline")
    asr_timeout: float = Field(default=10.0, description="Max seconds to wait for ASR result")
    asr_language: str = Field(default="en-US", description="ASR language/locale code")
    silence_timeout: float = Field(default=3.0, description="Seconds of silence before ending utterance")
    tts_voice: str = Field(default="Samantha", description="macOS TTS voice name")
    tts_enabled: bool = Field(default=True, description="Enable text-to-speech output")
    tts_speed: float = Field(default=150, description="TTS words per minute")
    text_linger: float = Field(default=3.0, description="Seconds to display text after TTS finishes")
    wake_word: WakeWordConfig = Field(default_factory=WakeWordConfig, description="Wake word detection settings")


class ClarvisAgentConfig(BaseModel):
    """Configuration for the Clarvis agent (model, tools, timeouts)."""

    model: str | None = Field(
        default=None, description="Claude model ID (e.g. 'claude-sonnet-4-6', 'claude-haiku-4-5')"
    )
    max_thinking_tokens: int | None = Field(default=None, description="Max thinking tokens (None = SDK default)")
    idle_timeout: float = Field(default=3600.0, description="Seconds before Clarvis agent disconnects")
    tools: dict[str, Any] = Field(
        default_factory=dict,
        description="Tool overrides for Clarvis agent",
    )


# ── Pi agent extra ─────────────────────────────────────────────────


class PiConfig(BaseModel):
    """Pi agent core bridge settings."""

    model_config = ConfigDict(extra="ignore")

    bridge_socket: str = Field(
        default="/tmp/clarvis-pi-agent.sock", description="Unix socket path for pi-bridge communication"
    )
    thinking_level: str = Field(
        default="off", description="Extended thinking level for Pi agent ('off', 'low', 'medium', 'high')"
    )


class WakeupConfig(BaseModel):
    """Autonomous wakeup prompt settings."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=True, description="Enable autonomous wakeup prompts")
    pulse_interval_minutes: int = Field(default=45, description="Minutes between regular pulse wakeups")
    context_sources: list[str] = Field(
        default_factory=lambda: ["time", "weather", "activity", "memory", "music"],
        description="Context sources to include in wakeup prompts",
    )


# ── MCP server ports ──────────────────────────────────────────────


class McpConfig(BaseModel):
    """MCP server port assignment."""

    model_config = ConfigDict(extra="ignore")

    standard_port: int = Field(default=7777, description="MCP tools for Claude Code (ping, context, stage_memory)")


# ── Channels extra ─────────────────────────────────────────────────


class ChannelsConfig(BaseModel):
    """Top-level settings for online chat channels (Discord, Telegram, etc.)."""

    model_config = ConfigDict(extra="ignore")  # per-channel dicts pass through

    model: str | None = Field(default=None, description="Claude model for Factoria (falls back to clarvis.model)")
    max_thinking_tokens: int | None = Field(
        default=None, description="Max thinking tokens (falls back to clarvis.max_thinking_tokens)"
    )
    idle_timeout: float | None = Field(
        default=None, description="Idle timeout in seconds (falls back to clarvis.idle_timeout)"
    )
    tools: dict[str, Any] = Field(
        default_factory=dict,
        description="Tool overrides for Factoria agent",
    )
    pi: PiConfig = Field(default_factory=PiConfig, description="Pi agent core bridge settings")
    wakeup: WakeupConfig = Field(default_factory=WakeupConfig, description="Autonomous wakeup prompt settings")
    admin_user_ids: list[str] = Field(
        default_factory=list,
        description="Channel user IDs that always receive admin role",
    )


# ── Root config ────────────────────────────────────────────────────


class WidgetConfig(BaseModel):
    """Main configuration combining all sections."""

    theme: ThemeConfig = Field(default_factory=ThemeConfig, description="Theme and color settings")
    display: DisplayConfig = Field(default_factory=DisplayConfig, description="Widget window display settings")
    testing: TestingConfig = Field(default_factory=TestingConfig, description="Development testing overrides")
    clarvis: ClarvisAgentConfig = Field(
        default_factory=ClarvisAgentConfig, description="Clarvis agent settings (model, tools, timeouts)"
    )
    voice: VoiceConfig = Field(default_factory=VoiceConfig, description="Voice I/O pipeline (TTS, ASR, wake word)")
    music: MusicConfig = Field(default_factory=MusicConfig, description="Music integration (Spotify)")
    memory: MemoryConfig = Field(default_factory=MemoryConfig, description="Dual memory system (Hindsight + Cognee)")
    mcp: McpConfig = Field(default_factory=McpConfig, description="MCP server port assignments")
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig, description="Factoria channel agent settings")

    @model_validator(mode="after")
    def _load_theme(self) -> "WidgetConfig":
        """Validate theme name and load color definitions."""
        if self.theme.base not in get_available_themes():
            self.theme.base = DEFAULT_THEME
        load_theme(self.theme.base, self.theme.overrides)
        return self

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "WidgetConfig":
        data = json_load_safe(path)
        if data is not None:
            return cls.model_validate(data)
        return cls()


# Global instance
_config: WidgetConfig | None = None


def get_config() -> WidgetConfig:
    """Get current config."""
    global _config
    if _config is None:
        _config = WidgetConfig.load()
    return _config
