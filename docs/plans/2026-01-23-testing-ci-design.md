# Testing & CI Design

**Date:** 2026-01-23
**Goal:** Catching regressions + documentation through behavioral tests

## Test Structure

```
tests/
├── conftest.py              # Shared fixtures (temp dirs, mock responses)
├── unit/
│   ├── test_weather.py      # Weather service + intensity calculation
│   ├── test_location.py     # Location service
│   ├── test_thinking_feed.py # Session parsing, thought extraction
│   ├── test_renderer.py     # Frame rendering, weather particles
│   ├── test_pipeline.py     # Layer compositing
│   ├── test_canvas.py       # Canvas operations
│   └── test_daemon.py       # Status processing, session tracking
├── integration/
│   └── test_daemon_flow.py  # End-to-end status → display flow
└── properties/
    └── test_properties.py   # Hypothesis tests for edge cases
```

## Coverage by Module

### Services (mocked external APIs)
- **test_weather.py** - `fetch_weather()` with mocked requests, `calculate_intensity()` for various conditions (clear→thunderstorm), edge cases (missing data)
- **test_location.py** - IP geolocation fallback, cached timezone handling
- **test_thinking_feed.py** - JSONL parsing, thought extraction, session lifecycle (active→idle→ended), incremental file reading

### Widget rendering (real filesystem for temp files)
- **test_renderer.py** - Frame output for each status, weather particle spawning, grid scaling
- **test_pipeline.py** - Layer priority, compositing, color handling
- **test_canvas.py** - Bounds checking, sprite rendering, cell operations

### Daemon (emphasis)
- **test_daemon.py** - Hook event processing (PreToolUse→running, PostToolUse→thinking, etc.), per-session history tracking, context persistence, history buffer limits (max 20)

### Property tests (hypothesis)
- Intensity calculation always returns 0-1 for any input
- Canvas operations never raise on out-of-bounds
- History buffers never exceed HISTORY_SIZE

## GitHub CI

**File:** `.github/workflows/test.yml`

```yaml
name: Tests
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --dev
      - run: uv run pytest --cov=central_hub --cov-report=xml
      - uses: codecov/codecov-action@v4
```

**Triggers:** Every push + PR
**Matrix:** Python 3.10 + 3.12 (min supported + latest)

## Dependencies

Add to `pyproject.toml`:

```toml
[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-cov>=4.0", "hypothesis>=6.0", "responses>=0.25"]
```

## Fixtures & Mocking

**conftest.py fixtures:**
- `temp_hub_files(tmp_path)` - Create temp files for daemon tests
- `mock_weather_api(responses)` - Mock Open-Meteo API responses
- `sample_hook_event()` - Sample PreToolUse hook event with context_window

**Mocking strategy:**
- `responses` library for HTTP mocking (weather, location APIs)
- Real `tmp_path` for file I/O (daemon, thinking feed)
- No mocking for pure functions (intensity calc, canvas ops)
