"""Wake word detection service backed by nanobuddy.

Uses nanobuddy.WakeDetector for streaming inference — 80ms chunks through
WakeEngine (incremental mel-spectrogram → embeddings → ONNX classifier)
with VAD gating and patience-based confirmation.
"""

import logging
from typing import Any, Callable, Optional

from ..widget.config import WakeWordConfig

logger = logging.getLogger(__name__)


class WakeWordService:
    """Clarvis wake word service using nanobuddy's WakeDetector."""

    def __init__(
        self,
        state_store: Any = None,
        config: Optional[WakeWordConfig] = None,
        on_detected: Optional[Callable[[], None]] = None,
    ):
        self.state_store = state_store
        self.config = config or WakeWordConfig()
        self._on_detected_callback = on_detected
        self._detector = None  # nanobuddy.WakeDetector, lazy import

    def start(self) -> bool:
        if not self.config.enabled:
            logger.info("Wake word service disabled in config")
            return False

        from nanobuddy import WakeDetector

        cfg = self.config

        def on_detected():
            if self._on_detected_callback:
                try:
                    self._on_detected_callback()
                except Exception as e:
                    logger.error(f"Detection callback failed: {e}")

        self._detector = WakeDetector(
            model_path=cfg.model_path,
            threshold=cfg.threshold,
            patience=cfg.patience,
            vad_threshold=cfg.vad_threshold,
            input_device=cfg.input_device,
            on_detected=on_detected,
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
