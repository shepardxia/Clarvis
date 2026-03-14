"""Voice infrastructure — wake word detection.

Wake word (nanobuddy): streaming inference with VAD gating and patience.
Leaf dependency of channels.voice.orchestrator.
"""

import logging
from typing import Any

from ..display.config import WakeWordConfig

logger = logging.getLogger(__name__)


# ── Wake word detection ──────────────────────────────────────────────
class WakeWordService:
    """Clarvis wake word service using nanobuddy's WakeDetector."""

    def __init__(
        self,
        config: WakeWordConfig | None = None,
        bus: Any = None,
    ):
        self.config = config or WakeWordConfig()
        self._bus = bus
        self._detector = None  # nanobuddy.WakeDetector, lazy import

    def start(self) -> bool:
        if not self.config.enabled:
            logger.info("Wake word service disabled in config")
            return False

        from nanobuddy import WakeDetector

        cfg = self.config

        def on_detected():
            self._bus.emit("wake_word:detected")

        def on_audio_lost(reason: str):
            logger.warning("Audio lost: %s", reason)
            self._bus.emit("wake_word:audio_lost", reason=reason)

        self._detector = WakeDetector(
            model_path=cfg.model_path,
            threshold=cfg.threshold,
            patience=cfg.patience,
            vad_threshold=cfg.vad_threshold,
            sample_rate=cfg.sample_rate,
            input_device=cfg.input_device,
            on_detected=on_detected,
            on_audio_lost=on_audio_lost,
            capture_dir=cfg.capture_dir,
            capture_seconds=cfg.capture_seconds,
        )
        return self._detector.start()

    def stop(self) -> None:
        if self._detector:
            self._detector.stop()
            self._detector = None

    @property
    def is_running(self) -> bool:
        return self._detector is not None and self._detector.is_running

    def pause(self) -> None:
        """Pause detection — stops mic and inference."""
        if self._detector:
            self._detector.pause()
            logger.info("Wake word detection paused")

    def resume(self) -> None:
        """Resume detection after a pause()."""
        if self._detector and not self._detector.is_running:
            self._detector.resume()
            logger.info("Wake word detection resumed")

    def mute(self) -> None:
        """Suppress detection without stopping mic (for TTS)."""
        if self._detector:
            self._detector.mute()

    def unmute(self) -> None:
        """Re-enable detection after TTS."""
        if self._detector:
            self._detector.unmute()
