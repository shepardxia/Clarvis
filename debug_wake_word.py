#!/usr/bin/env python3
"""Debug UI for wake word detection pipeline.

Shows live VAD speech activations, model probabilities, and detection events
in a curses-based terminal UI with scrolling history.

Optionally connects to the Clarvis daemon to display system state and
preview the context that would be prepended to voice commands.

Uses heybuddy.WakeWordDetector for the detection pipeline.
"""

import curses
import logging
import os
import sys
import time
import threading
import warnings
import numpy as np
from collections import deque
from pathlib import Path
from dataclasses import dataclass

from heybuddy import WakeWordDetector, DetectorConfig

MODEL_DIR = Path(__file__).resolve().parent / "models"

THRESHOLD = 0.3
VAD_THRESHOLD = 0.2
BAR_WIDTH = 40
DETECT_DISPLAY_SECS = 10
DAEMON_POLL_INTERVAL = 2.0


@dataclass
class Event:
    timestamp: float
    kind: str  # "vad", "model", "detect", "sim"
    value: float
    text: str


# ──────────────────────────────────────────────────────────────────────
# Daemon connection (optional — degrades gracefully if daemon is down)
# ──────────────────────────────────────────────────────────────────────

class DaemonConnection:
    """Polls the Clarvis daemon for state and voice context over IPC."""

    def __init__(self, poll_interval: float = DAEMON_POLL_INTERVAL):
        from clarvis.core.ipc import DaemonClient
        self._client = DaemonClient(timeout=2.0)
        self._poll_interval = poll_interval
        self._state: dict = {}
        self._voice_context: dict = {}
        self._connected = False
        self._lock = threading.Lock()
        self._stop = threading.Event()

    @property
    def connected(self) -> bool:
        return self._connected

    def get_state(self) -> dict:
        with self._lock:
            return self._state.copy()

    def get_voice_context(self) -> dict:
        with self._lock:
            return self._voice_context.copy()

    def start(self) -> None:
        t = threading.Thread(target=self._poll_loop, daemon=True)
        t.start()

    def stop(self) -> None:
        self._stop.set()

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                state = self._client.call("get_state")
                voice_ctx = self._client.call("get_voice_context")
                with self._lock:
                    self._state = state or {}
                    self._voice_context = voice_ctx or {}
                    self._connected = True
            except Exception:
                with self._lock:
                    self._connected = False
            self._stop.wait(self._poll_interval)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def make_bar(value: float, width: int, threshold: float = 0.0) -> str:
    filled = int(value * width)
    filled = max(0, min(filled, width))
    thresh_pos = int(threshold * width)
    bar = ""
    for i in range(width):
        if i < filled:
            bar += "\u2588"
        elif i == thresh_pos and threshold > 0:
            bar += "\u250a"
        else:
            bar += "\u2591"
    return bar


def _addnstr(scr, row, col, text, maxlen, attr=0):
    """Safe curses addnstr — silently ignores errors."""
    try:
        scr.addnstr(row, col, text, maxlen, attr)
    except curses.error:
        pass


# ──────────────────────────────────────────────────────────────────────
# Wake word detector thread
# ──────────────────────────────────────────────────────────────────────

def run_pipeline(events: deque, lock: threading.Lock, stop_event: threading.Event,
                 live_state: dict):
    """Background thread: run WakeWordDetector with callbacks.

    All stdout/stderr is suppressed so onnxruntime logs
    don't corrupt the curses display.
    """
    devnull = open(os.devnull, "w")
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = devnull
    sys.stderr = devnull
    warnings.filterwarnings("ignore")
    logging.disable(logging.CRITICAL)

    try:
        _run_pipeline_inner(events, lock, stop_event, live_state)
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        devnull.close()
        logging.disable(logging.NOTSET)


def _run_pipeline_inner(events, lock, stop_event, live_state):
    def on_audio(window, vad_prob, model_prob):
        now = time.time()
        rms = float(np.sqrt(np.mean(window ** 2)))
        peak = float(np.max(np.abs(window)))
        speech = vad_prob > VAD_THRESHOLD

        with lock:
            live_state["audio_rms"] = rms
            live_state["audio_peak"] = peak
            live_state["vad"] = vad_prob
            live_state["vad_speech"] = speech

            if speech:
                events.append(Event(now, "vad", vad_prob,
                                    f"Speech VAD={vad_prob:.3f}"))

            if model_prob > 0:
                live_state["model_prob"] = model_prob
                events.append(Event(
                    now, "model", model_prob,
                    f"prob={model_prob:.4f} VAD={vad_prob:.3f}",
                ))

    def on_detected():
        now = time.time()
        with lock:
            live_state["last_detect"] = now
            events.append(Event(
                now, "detect", 0,
                "*** DETECTED ***",
            ))

    config = DetectorConfig(
        model_path=str(MODEL_DIR / "clarvis_final.onnx"),
        threshold=THRESHOLD,
        vad_threshold=VAD_THRESHOLD,
        vad_model_path=str(MODEL_DIR / "silero-vad.onnx"),
    )

    with lock:
        live_state["status"] = "Loading models..."

    detector = WakeWordDetector(
        config=config,
        on_detected=on_detected,
        on_audio=on_audio,
    )
    detector.start()

    with lock:
        live_state["status"] = "Listening"

    stop_event.wait()
    detector.stop()


# ──────────────────────────────────────────────────────────────────────
# Curses UI
# ──────────────────────────────────────────────────────────────────────

def main(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(50)  # ~20 fps

    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, -1)
    curses.init_pair(2, curses.COLOR_YELLOW, -1)
    curses.init_pair(3, curses.COLOR_RED, -1)
    curses.init_pair(4, curses.COLOR_CYAN, -1)
    curses.init_pair(5, curses.COLOR_WHITE, -1)
    curses.init_pair(6, curses.COLOR_BLACK, curses.COLOR_RED)

    events = deque(maxlen=500)
    lock = threading.Lock()
    stop_event = threading.Event()
    live_state = {
        "status": "Loading models...",
        "audio_rms": 0.0,
        "audio_peak": 0.0,
        "vad": 0.0,
        "vad_speech": False,
        "model_prob": 0.0,
        "model_dur": 0.0,
        "last_detect": 0.0,
    }

    # Start wake word detector thread
    pipeline = threading.Thread(
        target=run_pipeline, args=(events, lock, stop_event, live_state),
        daemon=True,
    )
    pipeline.start()

    # Start daemon connection (optional)
    daemon = DaemonConnection()
    daemon.start()

    start_time = time.time()

    try:
        while True:
            key = stdscr.getch()
            if key == ord("q") or key == 27:
                break

            # ── Simulate voice command (s key) ──
            if key == ord("s") and daemon.connected:
                curses.echo()
                curses.curs_set(1)
                h_tmp, w_tmp = stdscr.getmaxyx()
                prompt = "Voice sim> "
                _addnstr(stdscr, h_tmp - 1, 0, prompt, w_tmp - 1,
                         curses.A_BOLD | curses.color_pair(4))
                stdscr.refresh()
                try:
                    sim_input = stdscr.getstr(
                        h_tmp - 1, len(prompt), w_tmp - len(prompt) - 1
                    ).decode("utf-8", errors="replace")
                except Exception:
                    sim_input = ""
                curses.noecho()
                curses.curs_set(0)

                if sim_input.strip():
                    vc = daemon.get_voice_context()
                    formatted = vc.get("formatted", "").strip()
                    preview = formatted.replace("\n", " | ") if formatted else "(no context)"
                    with lock:
                        events.append(Event(
                            time.time(), "sim", 0,
                            f"CTX: {preview}",
                        ))
                        events.append(Event(
                            time.time(), "sim", 0,
                            f"MSG: {sim_input}",
                        ))
                continue

            h, w = stdscr.getmaxyx()
            stdscr.erase()

            with lock:
                status = live_state["status"]
                audio_rms = live_state["audio_rms"]
                audio_peak = live_state["audio_peak"]
                vad = live_state["vad"]
                vad_speech = live_state["vad_speech"]
                model_prob = live_state["model_prob"]
                model_dur = live_state["model_dur"]
                last_detect = live_state["last_detect"]
                event_list = list(events)

            elapsed = time.time() - start_time
            since_detect = time.time() - last_detect if last_detect > 0 else -1

            row = 0

            # ── Header ──
            title = " Wake Word Debug "
            pad = max(0, (min(w, 80) - len(title)) // 2)
            header_line = "\u2550" * pad + title + "\u2550" * pad
            _addnstr(stdscr, row, 0, header_line, w - 1,
                     curses.A_BOLD | curses.color_pair(4))
            row += 1

            hints = "q=quit"
            if daemon.connected:
                hints += "  s=simulate"
            status_str = f" {status}  [{elapsed:.0f}s]  ({hints})"
            _addnstr(stdscr, row, 0, status_str, w - 1, curses.color_pair(5))
            row += 1

            # ── Detection banner ──
            if since_detect >= 0 and since_detect < DETECT_DISPLAY_SECS:
                banner = f"  *** WAKE WORD DETECTED ({since_detect:.1f}s ago) ***  "
                pad_l = max(0, (min(w, 80) - len(banner)) // 2)
                _addnstr(stdscr, row, 0, " " * pad_l + banner, w - 1,
                         curses.A_BOLD | curses.color_pair(6))
                row += 1
            elif since_detect >= 0:
                _addnstr(stdscr, row, 0, f" Last detection: {since_detect:.0f}s ago",
                         w - 1, curses.color_pair(5))
                row += 1
            else:
                _addnstr(stdscr, row, 0, " No detections yet",
                         w - 1, curses.color_pair(5))
                row += 1

            _addnstr(stdscr, row, 0, "\u2500" * min(w - 1, 80), w - 1,
                     curses.color_pair(5))
            row += 1

            # ── Live meters ──
            audio_bar = make_bar(min(audio_peak * 5, 1.0), BAR_WIDTH)
            _addnstr(stdscr, row, 0,
                     f" Audio \u2502 {audio_bar} \u2502 rms={audio_rms:.4f} peak={audio_peak:.3f}",
                     w - 1, curses.color_pair(5))
            row += 1

            vad_bar = make_bar(vad, BAR_WIDTH, VAD_THRESHOLD)
            vad_color = curses.color_pair(1) if vad_speech else curses.color_pair(5)
            speech_tag = " SPEECH" if vad_speech else ""
            _addnstr(stdscr, row, 0,
                     f"   VAD \u2502 {vad_bar} \u2502 {vad:.3f}{speech_tag}",
                     w - 1, vad_color)
            row += 1

            prob_bar = make_bar(min(model_prob * 2, 1.0), BAR_WIDTH, THRESHOLD * 2)
            if model_prob > THRESHOLD:
                prob_color = curses.color_pair(3) | curses.A_BOLD
            elif model_prob > 0.05:
                prob_color = curses.color_pair(2)
            else:
                prob_color = curses.color_pair(5)
            _addnstr(stdscr, row, 0,
                     f" Model \u2502 {prob_bar} \u2502 {model_prob:.4f} ({model_dur:.0f}ms)",
                     w - 1, prob_color)
            row += 1

            # ── Daemon state ──
            _addnstr(stdscr, row, 0, "\u2500" * min(w - 1, 80), w - 1,
                     curses.color_pair(5))
            row += 1

            if daemon.connected:
                ds = daemon.get_state()
                vc = daemon.get_voice_context()

                # Status line
                d_status = ds.get("status", {})
                line = f" Daemon \u2502 {d_status.get('status', '?')}"
                ctx_pct = vc.get("context_percent", 0)
                if ctx_pct > 0:
                    line += f"  ctx={ctx_pct:.0f}%"
                d_weather = vc.get("weather", {})
                if d_weather.get("temperature"):
                    line += f"  {d_weather['temperature']}F {d_weather.get('description', '')}"
                d_time = vc.get("time", "")
                if d_time:
                    line += f"  {d_time}"
                _addnstr(stdscr, row, 0, line, w - 1, curses.color_pair(4))
                row += 1

                # Voice context preview
                formatted = vc.get("formatted", "")
                if formatted:
                    # Compact: strip tags, join lines
                    preview = formatted.replace("<context>\n", "").replace("\n</context>", "")
                    preview = preview.strip().replace("\n", " \u2502 ")
                    _addnstr(stdscr, row, 0, f" Voice  \u2502 {preview}", w - 1,
                             curses.color_pair(2))
                    row += 1
                else:
                    _addnstr(stdscr, row, 0, " Voice  \u2502 (no context available)",
                             w - 1, curses.color_pair(5))
                    row += 1
            else:
                _addnstr(stdscr, row, 0, " Daemon \u2502 not connected",
                         w - 1, curses.color_pair(5))
                row += 1

            # ── Event log header ──
            _addnstr(stdscr, row, 0, "\u2500" * min(w - 1, 80), w - 1,
                     curses.color_pair(5))
            row += 1

            header = " Time     \u2502 Event  \u2502 Details"
            _addnstr(stdscr, row, 0, header, w - 1,
                     curses.A_BOLD | curses.color_pair(4))
            row += 1

            # ── Event log ──
            max_events = h - row - 1
            visible = event_list[-max_events:] if max_events > 0 else []

            for ev in visible:
                if row >= h - 1:
                    break

                ts = ev.timestamp - start_time
                ts_str = f" {ts:7.1f}s"

                if ev.kind == "detect":
                    color = curses.color_pair(3) | curses.A_BOLD
                    kind = "DETECT"
                elif ev.kind == "model":
                    if ev.value > THRESHOLD:
                        color = curses.color_pair(3)
                    elif ev.value > 0.05:
                        color = curses.color_pair(2)
                    else:
                        color = curses.color_pair(5)
                    kind = "MODEL "
                elif ev.kind == "vad":
                    color = curses.color_pair(1)
                    kind = "VAD   "
                elif ev.kind == "sim":
                    color = curses.color_pair(2) | curses.A_BOLD
                    kind = "SIM   "
                else:
                    color = curses.color_pair(5)
                    kind = ev.kind[:6].ljust(6)

                line = f"{ts_str} \u2502 {kind} \u2502 {ev.text}"
                _addnstr(stdscr, row, 0, line, w - 1, color)
                row += 1

            stdscr.refresh()

    finally:
        daemon.stop()
        stop_event.set()
        pipeline.join(timeout=3.0)


if __name__ == "__main__":
    curses.wrapper(main)
