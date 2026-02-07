#!/usr/bin/env python3
"""Minimal wake word debug — no curses, no log suppression.

Run this to see raw pipeline output and diagnose issues.
Press Ctrl+C to stop.
"""

import logging
import time
from pathlib import Path

import numpy as np
from heybuddy import DetectorConfig, WakeWordDetector

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(name)s %(levelname)s: %(message)s",
)

MODEL_DIR = Path(__file__).resolve().parent / "models"
THRESHOLD = 0.3
VAD_THRESHOLD = 0.2


def on_audio(window, vad_prob, model_prob):
    rms = float(np.sqrt(np.mean(window**2)))
    speech = vad_prob > VAD_THRESHOLD
    parts = [f"rms={rms:.4f} vad={vad_prob:.3f}"]
    if speech:
        parts.append("SPEECH")
    if model_prob > 0:
        parts.append(f"model={model_prob:.4f}")
    if model_prob > THRESHOLD:
        parts.append("*** ABOVE THRESHOLD ***")
    print(" | ".join(parts))


def on_detected():
    print("\n=== WAKE WORD DETECTED ===\n")


def main():
    config = DetectorConfig(
        model_path=str(MODEL_DIR / "clarvis_final.onnx"),
        threshold=THRESHOLD,
        vad_threshold=VAD_THRESHOLD,
        vad_model_path=str(MODEL_DIR / "silero-vad.onnx"),
    )

    detector = WakeWordDetector(
        config=config,
        on_detected=on_detected,
        on_audio=on_audio,
    )

    print(f"Model: {config.model_path}")
    print(f"Threshold: {THRESHOLD}  VAD: {VAD_THRESHOLD}")
    print("Starting detector...")
    detector.start()

    try:
        while True:
            time.sleep(0.5)
            if not detector.is_running:
                print("Detector stopped unexpectedly!")
                break
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        detector.stop()
        print("Done.")


if __name__ == "__main__":
    main()
