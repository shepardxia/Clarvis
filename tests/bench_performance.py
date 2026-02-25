#!/usr/bin/env python3
"""Clarvis performance benchmarks.

Measures rendering pipeline, startup, and event processing latency.
Run: .venv/bin/python tests/bench_performance.py
"""

import json
import statistics
import sys
import threading
import time
from pathlib import Path

# Ensure clarvis package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── Timing harness ───────────────────────────────────────────────────


def _measure(fn, iterations=1000, warmup=100):
    """Time fn() over iterations after warmup. Returns list of durations in ns."""
    for _ in range(warmup):
        fn()
    times = []
    for _ in range(iterations):
        t0 = time.perf_counter_ns()
        fn()
        times.append(time.perf_counter_ns() - t0)
    return times


def _report(name, times_ns, extra=""):
    """Print stats for a benchmark."""
    times_us = [t / 1000 for t in times_ns]
    mean = statistics.mean(times_us)
    std = statistics.stdev(times_us) if len(times_us) > 1 else 0
    p50 = statistics.median(times_us)
    sorted_t = sorted(times_us)
    p95 = sorted_t[int(len(sorted_t) * 0.95)]
    p99 = sorted_t[int(len(sorted_t) * 0.99)]
    ops = 1_000_000 / mean if mean > 0 else float("inf")

    unit = "μs"
    vals = [mean, std, p50, p95, p99]
    if mean >= 1000:
        unit = "ms"
        vals = [v / 1000 for v in vals]

    extra_str = f"  {extra}" if extra else ""
    print(
        f"  {name:<32} "
        f"mean={vals[0]:>8.1f}{unit}  std={vals[1]:>7.1f}{unit}  "
        f"p50={vals[2]:>8.1f}{unit}  p95={vals[3]:>8.1f}{unit}  p99={vals[4]:>8.1f}{unit}  "
        f"ops={ops:>10,.0f}/s{extra_str}"
    )
    return mean  # return mean in μs


# ── Shared setup ─────────────────────────────────────────────────────


def _make_registry():
    from clarvis.display.elements.registry import ElementRegistry

    reg = ElementRegistry()
    reg.load_all()
    return reg


def _make_renderer():
    from clarvis.display.renderer import FrameRenderer

    return FrameRenderer(width=43, height=17)


# ── Tier 1: Rendering (HOT — 3 FPS) ─────────────────────────────────


def bench_rendering():
    print("\n═══ Tier 1: Rendering (3 FPS budget = 333ms) ═══\n")
    renderer = _make_renderer()

    # Set up weather for worst-case (rain, high intensity)
    renderer.weather.set_weather("rain", intensity=0.8, wind_speed=5.0)
    renderer.face.set_status("thinking")

    # Warm up Numba JIT
    for _ in range(20):
        renderer.weather.tick()

    # --- Full frame render ---
    def full_render():
        renderer.face.tick()
        renderer.weather.tick()
        renderer.render_grid(context_percent=42.0)

    times = _measure(full_render, iterations=500, warmup=50)
    total_mean = _report("full frame render", times)

    # --- Face render (cache hit) ---
    layer = renderer.avatar_layer

    def face_render():
        layer.clear()
        renderer.face.render(layer, renderer.avatar_x, renderer.avatar_y, color=15)

    times = _measure(face_render, iterations=2000, warmup=200)
    _report("face render (cache hit)", times)

    # --- Face tick ---
    times = _measure(renderer.face.tick, iterations=5000, warmup=500)
    _report("face tick", times)

    # --- Face status switch (cache hit) ---
    statuses = ["idle", "thinking", "reading", "writing", "executing"]
    idx = [0]

    def status_switch():
        idx[0] = (idx[0] + 1) % len(statuses)
        renderer.face.set_status(statuses[idx[0]])

    times = _measure(status_switch, iterations=2000, warmup=200)
    _report("face status switch", times)

    # --- Weather tick ---
    times = _measure(renderer.weather.tick, iterations=1000, warmup=100)
    _report("weather tick (rain)", times)

    # --- Weather render ---
    wlayer = renderer.weather_layer

    def weather_render():
        wlayer.clear()
        renderer.weather.render(wlayer, color=8)

    times = _measure(weather_render, iterations=1000, warmup=100)
    _report("weather render", times)

    # --- Pipeline composite (to_grid) ---
    # Pre-render content into layers so composite has work to do
    renderer.face.render(renderer.avatar_layer, renderer.avatar_x, renderer.avatar_y)
    renderer.weather.render(renderer.weather_layer, color=8)
    renderer.progress.render(renderer.bar_layer, renderer.bar_x, renderer.bar_y, percent=42.0)

    times = _measure(renderer.pipeline.to_grid, iterations=1000, warmup=100)
    _report("pipeline composite (to_grid)", times)

    # --- Frame serialization (json) ---
    rows, cell_colors = renderer.pipeline.to_grid()
    frame_data = {
        "rows": rows,
        "cell_colors": cell_colors,
        "theme_color": [200, 50, 100],
    }
    payload_size = len(json.dumps(frame_data).encode())

    def serialize_json():
        json.dumps(frame_data).encode("utf-8")

    times = _measure(serialize_json, iterations=2000, warmup=200)
    _report("frame serialize (json)", times, extra=f"({payload_size:,} bytes)")

    # --- Frame serialization (orjson) ---
    try:
        import orjson

        payload_size_orjson = len(orjson.dumps(frame_data))

        def serialize_orjson():
            orjson.dumps(frame_data)

        times = _measure(serialize_orjson, iterations=2000, warmup=200)
        _report("frame serialize (orjson)", times, extra=f"({payload_size_orjson:,} bytes)")
    except ImportError:
        print("  frame serialize (orjson)        [not installed]")

    # Budget check
    print(f"\n  Budget: {total_mean / 1000:.1f}ms / 333ms per frame ({total_mean / 3330:.1%} utilization)")


# ── Tier 2: Startup (COLD — one-time) ───────────────────────────────


def bench_startup():
    print("\n═══ Tier 2: Startup ═══\n")

    # --- Registry load ---
    from clarvis.display.elements.registry import ElementRegistry

    def registry_load():
        reg = ElementRegistry()
        reg.load_all()
        return reg

    times = _measure(registry_load, iterations=10, warmup=1)
    _report("registry load (137 YAML)", times)

    # --- Face prewarm ---
    reg = _make_registry()

    from clarvis.display.archetypes.face import FaceArchetype

    def face_prewarm():
        face = FaceArchetype(reg)
        stats = face.prewarm_cache()
        return stats

    times = _measure(face_prewarm, iterations=10, warmup=1)
    stats = face_prewarm()
    total_frames = sum(stats.values())
    _report("face prewarm", times, extra=f"({total_frames} frames, {len(stats)} statuses)")

    # --- Progress prewarm ---
    from clarvis.display.archetypes.progress import ProgressArchetype

    def progress_prewarm():
        prog = ProgressArchetype(reg, width=11)
        return prog.prewarm_cache()

    times = _measure(progress_prewarm, iterations=20, warmup=2)
    pstats = progress_prewarm()
    _report("progress prewarm", times, extra=f"({pstats['cached_percentages']} pcts, {pstats['memory_bytes']} bytes)")

    # --- Weather shape prewarm ---
    from clarvis.display.archetypes.weather import WeatherArchetype

    def weather_prewarm():
        w = WeatherArchetype(reg, 43, 17)
        return w.prewarm_shapes()

    times = _measure(weather_prewarm, iterations=10, warmup=1)
    wstats = weather_prewarm()
    _report("weather shape prewarm", times, extra=f"({len(wstats)} types: {wstats})")

    # --- Full renderer init (all of the above combined) ---
    times = _measure(_make_renderer, iterations=5, warmup=1)
    _report("full renderer init", times)


# ── Tier 3: Event Processing (WARM — per tool use) ──────────────────


def bench_events():
    print("\n═══ Tier 3: Event Processing ═══\n")

    from clarvis.core.state import StateStore
    from clarvis.hooks.hook_processor import HookProcessor
    from clarvis.hooks.tool_classifier import classify_tool
    from clarvis.services.session_tracker import SessionTracker

    # --- Tool classification ---
    tools = [
        "Read",
        "Write",
        "Bash",
        "Grep",
        "Edit",
        "Glob",
        "Task",
        "mcp__clarvis__ping",
        "mcp__serena__find_symbol",
        "UnknownTool",
    ]

    idx = [0]

    def classify():
        idx[0] = (idx[0] + 1) % len(tools)
        return classify_tool(tools[idx[0]])

    times = _measure(classify, iterations=10000, warmup=1000)
    _report("tool classification", times)

    # --- Hook event processing ---
    state = StateStore()
    tracker = SessionTracker(state)
    processor = HookProcessor(state, tracker)

    events = [
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
            "session_id": "s1",
            "context_window": {"used": 5000, "total": 200000},
        },
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "Read",
            "session_id": "s1",
            "context_window": {"used": 6000, "total": 200000},
        },
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "session_id": "s1",
            "context_window": {"used": 7000, "total": 200000},
        },
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "session_id": "s1",
            "context_window": {"used": 8000, "total": 200000},
        },
        {"hook_event_name": "UserPromptSubmit", "session_id": "s2", "context_window": {"used": 1000, "total": 200000}},
        {"hook_event_name": "Stop", "session_id": "s1", "context_window": {"used": 10000, "total": 200000}},
    ]

    eidx = [0]

    def process_event():
        eidx[0] = (eidx[0] + 1) % len(events)
        processor.process_hook_event(events[eidx[0]])

    times = _measure(process_event, iterations=5000, warmup=500)
    _report("hook event processing", times)

    # --- State store update (0 observers) ---
    store_0 = StateStore()
    counter = [0]

    def update_0():
        counter[0] += 1
        store_0.update("status", {"status": "thinking", "n": counter[0]})

    times = _measure(update_0, iterations=10000, warmup=1000)
    _report("state update (0 observers)", times)

    # --- State store update (5 observers) ---
    store_5 = StateStore()
    for _ in range(5):
        store_5.subscribe(lambda section, value: None)

    counter2 = [0]

    def update_5():
        counter2[0] += 1
        store_5.update("status", {"status": "reading", "n": counter2[0]})

    times = _measure(update_5, iterations=10000, warmup=1000)
    _report("state update (5 observers)", times)

    # --- State store read under concurrent writes ---
    store_c = StateStore()
    store_c.update("weather", {"temperature": 72, "description": "clear"})
    running = threading.Event()
    running.set()

    def writer():
        i = 0
        while running.is_set():
            i += 1
            store_c.update("status", {"status": "thinking", "i": i})

    writer_thread = threading.Thread(target=writer, daemon=True)
    writer_thread.start()

    def read_weather():
        store_c.get("weather")

    times = _measure(read_weather, iterations=5000, warmup=500)
    running.clear()
    writer_thread.join(timeout=2)
    _report("state read (concurrent writes)", times)


# ── Memory report ────────────────────────────────────────────────────


def report_memory():
    print("\n═══ Memory Footprint ═══\n")
    renderer = _make_renderer()

    # Face cache
    face_bytes = sum(sum(m.nbytes for m in frames) for frames in renderer.face._state_cache.values())
    face_frames = sum(len(f) for f in renderer.face._state_cache.values())
    print(f"  Face cache:     {face_frames:>4} frames, {face_bytes:>8,} bytes ({face_bytes / 1024:.1f} KB)")

    # Progress cache
    prog_bytes = sum(c.nbytes + col.nbytes for c, col in renderer.progress._percent_cache.values())
    print(
        f"  Progress cache: {len(renderer.progress._percent_cache):>4} entries,"
        f" {prog_bytes:>8,} bytes ({prog_bytes / 1024:.1f} KB)"
    )

    # Weather arrays
    weather_bytes = (
        renderer.weather.p_x.nbytes
        + renderer.weather.p_y.nbytes
        + renderer.weather.p_vx.nbytes
        + renderer.weather.p_vy.nbytes
        + renderer.weather.p_age.nbytes
        + renderer.weather.p_lifetime.nbytes
        + renderer.weather.p_shape_idx.nbytes
    )
    print(
        f"  Weather arrays: {len(renderer.weather.p_x):>4} slots,"
        f"  {weather_bytes:>8,} bytes ({weather_bytes / 1024:.1f} KB)"
    )

    # Pipeline buffers
    pipe_bytes = renderer.pipeline.out_chars.nbytes + renderer.pipeline.out_colors.nbytes
    print(
        f"  Pipeline bufs:  {renderer.width}x{renderer.height} grid,"
        f" {pipe_bytes:>8,} bytes ({pipe_bytes / 1024:.1f} KB)"
    )

    total = face_bytes + prog_bytes + weather_bytes + pipe_bytes
    print(f"\n  Total:          {total:>8,} bytes ({total / 1024:.1f} KB)")


# ── Main ─────────────────────────────────────────────────────────────


def main():
    print("╔════════════════════════════════════════════════╗")
    print("║     Clarvis Performance Benchmarks             ║")
    print("╚════════════════════════════════════════════════╝")

    bench_rendering()
    bench_startup()
    bench_events()
    report_memory()

    print("\n✓ All benchmarks complete.\n")


if __name__ == "__main__":
    main()
