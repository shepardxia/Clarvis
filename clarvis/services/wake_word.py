"""Wake word detection service — thin wrapper around heybuddy.WakeWordDetector.

Adds Clarvis-specific behaviour: state_store update on detection.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from heybuddy import DetectorConfig, WakeWordDetector

logger = logging.getLogger(__name__)

# Clarvis/models/ — two levels up from clarvis/services/
DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[2] / "models"


@dataclass
class WakeWordConfig:
    """Clarvis-side configuration (serialised in config.json)."""

    enabled: bool = False
    model_path: Path = field(default_factory=lambda: DEFAULT_MODEL_DIR / "clarvis_final.onnx")
    threshold: float = 0.75
    vad_threshold: float = 0.75
    cooldown: float = 2.0
    input_device: Optional[str] = None
    use_int8: bool = False

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "model_path": str(self.model_path),
            "threshold": self.threshold,
            "vad_threshold": self.vad_threshold,
            "cooldown": self.cooldown,
            "input_device": self.input_device,
            "use_int8": self.use_int8,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WakeWordConfig":
        if not isinstance(d, dict):
            return cls()
        model_path = d.get("model_path")
        if model_path:
            model_path = Path(model_path).expanduser()
        else:
            model_path = DEFAULT_MODEL_DIR / "clarvis_final.onnx"
        return cls(
            enabled=d.get("enabled", False),
            model_path=model_path,
            threshold=d.get("threshold", 0.75),
            vad_threshold=d.get("vad_threshold", 0.75),
            cooldown=d.get("cooldown", 2.0),
            input_device=d.get("input_device"),
            use_int8=d.get("use_int8", False),
        )


class WakeWordService:
    """Clarvis wake word service delegating to heybuddy.WakeWordDetector."""

    def __init__(
        self,
        state_store: Any = None,
        config: Optional[WakeWordConfig] = None,
        on_detected: Optional[Callable[[], None]] = None,
    ):
        self.state_store = state_store
        self.config = config or WakeWordConfig()
        self._on_detected_callback = on_detected
        self._detector: Optional[WakeWordDetector] = None

    def start(self) -> bool:
        if not self.config.enabled:
            logger.info("Wake word service disabled in config")
            return False

        cfg = self.config
        vad_path = cfg.model_path.parent / "silero-vad.onnx"
        detector_config = DetectorConfig(
            model_path=str(cfg.model_path),
            threshold=cfg.threshold,
            vad_threshold=cfg.vad_threshold,
            cooldown=cfg.cooldown,
            input_device=cfg.input_device,
            vad_model_path=str(vad_path) if vad_path.exists() else None,
        )

        def on_detected():
            if self._on_detected_callback:
                try:
                    self._on_detected_callback()
                except Exception as e:
                    logger.error(f"Detection callback failed: {e}")

        self._detector = WakeWordDetector(config=detector_config, on_detected=on_detected)
        return self._detector.start()

    def stop(self) -> None:
        if self._detector:
            self._detector.stop()
            self._detector = None

    @property
    def is_running(self) -> bool:
        return self._detector is not None and self._detector.is_running

    def pause(self) -> None:
        """Pause detection without destroying the service.

        Stops the detector so the mic is released and no false triggers
        occur during ASR.  Call resume() to restart.
        """
        if self._detector:
            self._detector.stop()
            logger.info("Wake word detection paused")

    def resume(self) -> None:
        """Resume detection after a pause().

        Rebuilds the detector from the current config so the audio
        pipeline is fully restarted.
        """
        if self._detector is None:
            return
        # Detector was stopped but not None'd — restart it
        if not self._detector.is_running:
            self._detector.start()
            logger.info("Wake word detection resumed")
