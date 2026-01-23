#!/usr/bin/env python3
"""Debug UI for Clarvis Widget - control rendering parameters in real-time."""

import json
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from .widget.config import WidgetConfig, get_config, set_config, CONFIG_PATH
from .widget.renderer import FrameRenderer, ANIMATION_KEYFRAMES, STATUS_COLORS
from .core import read_hub_data
from .daemon import CentralHubDaemon

# Status file paths
STATUS_RAW_FILE = Path("/tmp/claude-status-raw.json")
HUB_DATA_FILE = Path("/tmp/central-hub-data.json")

# Global daemon instance for status watching
daemon_instance: CentralHubDaemon = None

# Global state
renderer: FrameRenderer = None
config: WidgetConfig = None
running = True
lock = threading.Lock()


def init_renderer():
    """Initialize renderer from config."""
    global renderer, config
    config = get_config()
    renderer = FrameRenderer(width=config.grid_width, height=config.grid_height)
    apply_config_to_renderer()


def apply_config_to_renderer():
    """Apply current config to renderer."""
    global renderer, config

    # Recreate if grid size changed
    if renderer.width != config.grid_width or renderer.height != config.grid_height:
        renderer = FrameRenderer(width=config.grid_width, height=config.grid_height)

    # Apply offsets (recalculate layout first, then apply offsets)
    renderer._recalculate_layout()
    renderer.avatar_x += config.avatar_x_offset
    renderer.avatar_y += config.avatar_y_offset
    renderer.bar_y += config.bar_y_offset

    # Apply weather
    renderer.set_weather(config.weather_type, config.weather_intensity)

    # Apply status override if set
    if config.status_override:
        renderer.set_status(config.status_override)


HTML_PAGE = """<!DOCTYPE html>
<html>
<head>
    <title>Clarvis Debug UI</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'SF Mono', Monaco, monospace;
            background: #1a1a2e;
            color: #eee;
            padding: 20px;
            display: flex;
            gap: 20px;
        }
        .panel {
            background: #16213e;
            border-radius: 12px;
            padding: 20px;
            min-width: 300px;
        }
        h2 {
            color: #0f9;
            margin-bottom: 15px;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .control {
            margin-bottom: 15px;
        }
        label {
            display: block;
            margin-bottom: 5px;
            color: #888;
            font-size: 12px;
        }
        select, input[type="range"], input[type="number"] {
            width: 100%;
            padding: 8px;
            background: #0f0f23;
            border: 1px solid #333;
            border-radius: 6px;
            color: #fff;
            font-size: 14px;
        }
        input[type="range"] {
            padding: 0;
            height: 24px;
        }
        .value {
            text-align: right;
            color: #0f9;
            font-size: 12px;
            margin-top: 2px;
        }
        .preview {
            background: #0a0a14;
            border-radius: 8px;
            padding: 15px;
            font-family: 'SF Mono', Monaco, 'Courier New', monospace;
            font-size: 13px;
            line-height: 1.3;
            white-space: pre;
            color: #0f9;
            min-height: 200px;
            border: 2px solid #333;
        }
        .btn {
            background: #0f9;
            color: #000;
            border: none;
            padding: 10px 20px;
            border-radius: 6px;
            cursor: pointer;
            font-weight: bold;
            margin-right: 10px;
            margin-top: 10px;
        }
        .btn:hover { background: #0da; }
        .btn.danger { background: #f55; color: #fff; }
        .btn.secondary { background: #444; color: #fff; }
        .row { display: flex; gap: 10px; }
        .row > * { flex: 1; }
        .saved {
            color: #0f9;
            font-size: 11px;
            margin-left: 10px;
            opacity: 0;
            transition: opacity 0.3s;
        }
        .saved.show { opacity: 1; }
        .section { margin-bottom: 20px; padding-bottom: 15px; border-bottom: 1px solid #333; }
        .config-path {
            font-size: 10px;
            color: #555;
            margin-top: 15px;
            word-break: break-all;
        }
        .status-box {
            background: #0a0a14;
            border-radius: 6px;
            padding: 12px;
            border: 1px solid #333;
        }
        .status-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 4px 0;
            border-bottom: 1px solid #222;
        }
        .status-item:last-child { border-bottom: none; }
        .status-label {
            color: #666;
            font-size: 11px;
        }
        .status-value {
            color: #0f9;
            font-size: 12px;
            font-weight: 500;
        }
        .status-value.mono {
            font-family: 'SF Mono', Monaco, monospace;
            font-size: 10px;
        }
        .color-swatch {
            width: 12px;
            height: 12px;
            border-radius: 3px;
            margin-left: 8px;
            border: 1px solid #444;
        }
        .raw-json {
            background: #0a0a14;
            border-radius: 6px;
            padding: 10px;
            font-size: 10px;
            line-height: 1.4;
            color: #888;
            max-height: 200px;
            overflow: auto;
            white-space: pre-wrap;
            word-break: break-all;
            border: 1px solid #333;
            margin-top: 8px;
        }
        .btn-small {
            background: #333;
            color: #888;
            border: none;
            padding: 3px 8px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 10px;
            margin-left: 10px;
        }
        .btn-small:hover { background: #444; color: #fff; }
        .status-value.event-running { color: #0f9; }
        .status-value.event-thinking { color: #ff0; }
        .status-value.event-awaiting { color: #0af; }
        .status-value.event-idle { color: #888; }
    </style>
</head>
<body>
    <div class="panel">
        <h2>Avatar State <span class="saved" id="savedIndicator">Saved!</span></h2>
        <div class="section">
            <div class="control">
                <label>Status Override (blank = use hooks)</label>
                <select id="status_override" onchange="update()">
                    <option value="">(from hooks)</option>
                    <option value="idle">idle</option>
                    <option value="resting">resting</option>
                    <option value="thinking">thinking</option>
                    <option value="running">running</option>
                    <option value="executing">executing</option>
                    <option value="awaiting">awaiting</option>
                    <option value="reading">reading</option>
                    <option value="writing">writing</option>
                    <option value="reviewing">reviewing</option>
                    <option value="offline">offline</option>
                </select>
            </div>
            <div class="control">
                <label>Context % Override</label>
                <input type="range" id="context_percent_override" min="0" max="100" value="50" oninput="update()">
                <div class="value" id="context_percent_override_val">50%</div>
            </div>
        </div>

        <h2>Weather</h2>
        <div class="section">
            <div class="control">
                <label>Type</label>
                <select id="weather_type" onchange="update()">
                    <option value="auto">(from real weather)</option>
                    <option value="clear">clear</option>
                    <option value="snow">snow</option>
                    <option value="rain">rain</option>
                    <option value="cloudy">cloudy</option>
                    <option value="fog">fog</option>
                    <option value="windy">windy</option>
                </select>
            </div>
            <div class="control">
                <label>Intensity</label>
                <input type="range" id="weather_intensity" min="0" max="1" step="0.1" value="0.6" oninput="update()">
                <div class="value" id="weather_intensity_val">0.6</div>
            </div>
        </div>

        <h2>Grid Size</h2>
        <div class="section">
            <div class="row">
                <div class="control">
                    <label>Width</label>
                    <input type="number" id="grid_width" min="12" max="40" value="18" onchange="update()">
                </div>
                <div class="control">
                    <label>Height</label>
                    <input type="number" id="grid_height" min="8" max="30" value="10" onchange="update()">
                </div>
            </div>
        </div>

        <h2>Position Offsets</h2>
        <div class="section">
            <div class="row">
                <div class="control">
                    <label>Avatar X</label>
                    <input type="number" id="avatar_x_offset" min="-10" max="10" value="0" onchange="update()">
                </div>
                <div class="control">
                    <label>Avatar Y</label>
                    <input type="number" id="avatar_y_offset" min="-10" max="10" value="0" onchange="update()">
                </div>
            </div>
            <div class="control">
                <label>Bar Y Offset</label>
                <input type="number" id="bar_y_offset" min="-5" max="5" value="0" onchange="update()">
            </div>
        </div>

        <h2>Animation</h2>
        <div class="control">
            <label>FPS</label>
            <input type="range" id="fps" min="1" max="15" value="5" oninput="update()">
            <div class="value" id="fps_val">5 fps</div>
        </div>
        <button class="btn secondary" id="pauseBtn" onclick="togglePause()">Pause</button>
        <button class="btn" onclick="resetDefaults()">Reset</button>

        <div class="config-path">Config: """ + str(CONFIG_PATH) + """</div>
    </div>

    <div class="panel" style="flex: 1;">
        <h2>Live Preview</h2>
        <div class="preview" id="preview">Loading...</div>
        <div style="margin-top: 15px; font-size: 11px; color: #666;">
            Changes are saved to config and applied to the real widget instantly.
        </div>
    </div>

    <div class="panel" style="min-width: 350px;">
        <h2>Status Hooks Debug</h2>
        <div class="section">
            <label>Parsed Status</label>
            <div class="status-box" id="parsedStatus">
                <div class="status-item">
                    <span class="status-label">Status:</span>
                    <span class="status-value" id="parsed_status">--</span>
                </div>
                <div class="status-item">
                    <span class="status-label">Color:</span>
                    <span class="status-value" id="parsed_color">--</span>
                    <span class="color-swatch" id="color_swatch"></span>
                </div>
                <div class="status-item">
                    <span class="status-label">Context:</span>
                    <span class="status-value" id="parsed_context">--</span>
                </div>
                <div class="status-item">
                    <span class="status-label">Updated:</span>
                    <span class="status-value" id="parsed_timestamp">--</span>
                </div>
            </div>
        </div>
        <div class="section">
            <label>Raw Hook Event</label>
            <div class="status-box" id="rawHookEvent">
                <div class="status-item">
                    <span class="status-label">Event:</span>
                    <span class="status-value" id="raw_event">--</span>
                </div>
                <div class="status-item">
                    <span class="status-label">Session:</span>
                    <span class="status-value mono" id="raw_session">--</span>
                </div>
                <div class="status-item">
                    <span class="status-label">Model:</span>
                    <span class="status-value" id="raw_model">--</span>
                </div>
                <div class="status-item">
                    <span class="status-label">Cost:</span>
                    <span class="status-value" id="raw_cost">--</span>
                </div>
                <div class="status-item">
                    <span class="status-label">Context Window:</span>
                    <span class="status-value" id="raw_context_window">--</span>
                </div>
            </div>
        </div>
        <div class="section" style="border-bottom: none;">
            <label>Raw JSON <button class="btn-small" onclick="toggleRawJson()">Toggle</button></label>
            <pre class="raw-json" id="rawJson" style="display: none;">Loading...</pre>
        </div>
    </div>

<script>
    let paused = false;

    // Load current config on page load
    fetch('/api/config')
        .then(r => r.json())
        .then(cfg => {
            document.getElementById('status_override').value = cfg.status_override || '';
            document.getElementById('context_percent_override').value = cfg.context_percent_override || 50;
            document.getElementById('weather_type').value = cfg.weather_type || 'clear';
            document.getElementById('weather_intensity').value = cfg.weather_intensity || 0.6;
            document.getElementById('grid_width').value = cfg.grid_width || 18;
            document.getElementById('grid_height').value = cfg.grid_height || 10;
            document.getElementById('avatar_x_offset').value = cfg.avatar_x_offset || 0;
            document.getElementById('avatar_y_offset').value = cfg.avatar_y_offset || 0;
            document.getElementById('bar_y_offset').value = cfg.bar_y_offset || 0;
            document.getElementById('fps').value = cfg.fps || 5;
            paused = cfg.paused || false;
            updateDisplayValues();
            updatePauseBtn();
        });

    function updateDisplayValues() {
        document.getElementById('context_percent_override_val').textContent =
            document.getElementById('context_percent_override').value + '%';
        document.getElementById('weather_intensity_val').textContent =
            parseFloat(document.getElementById('weather_intensity').value).toFixed(1);
        document.getElementById('fps_val').textContent =
            document.getElementById('fps').value + ' fps';
    }

    function updatePauseBtn() {
        document.getElementById('pauseBtn').textContent = paused ? 'Resume' : 'Pause';
        document.getElementById('pauseBtn').className = paused ? 'btn danger' : 'btn secondary';
    }

    function showSaved() {
        const el = document.getElementById('savedIndicator');
        el.classList.add('show');
        setTimeout(() => el.classList.remove('show'), 1500);
    }

    function update() {
        const statusVal = document.getElementById('status_override').value;
        const contextVal = document.getElementById('context_percent_override').value;

        const data = {
            status_override: statusVal || null,
            context_percent_override: statusVal ? parseFloat(contextVal) : null,
            weather_type: document.getElementById('weather_type').value,
            weather_intensity: parseFloat(document.getElementById('weather_intensity').value),
            grid_width: parseInt(document.getElementById('grid_width').value),
            grid_height: parseInt(document.getElementById('grid_height').value),
            avatar_x_offset: parseInt(document.getElementById('avatar_x_offset').value),
            avatar_y_offset: parseInt(document.getElementById('avatar_y_offset').value),
            bar_y_offset: parseInt(document.getElementById('bar_y_offset').value),
            fps: parseInt(document.getElementById('fps').value),
            paused: paused
        };

        updateDisplayValues();

        fetch('/api/config', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(data)
        }).then(() => showSaved());
    }

    function togglePause() {
        paused = !paused;
        updatePauseBtn();
        update();
    }

    function resetDefaults() {
        document.getElementById('status_override').value = '';
        document.getElementById('context_percent_override').value = '50';
        document.getElementById('weather_type').value = 'clear';
        document.getElementById('weather_intensity').value = '0.6';
        document.getElementById('grid_width').value = '18';
        document.getElementById('grid_height').value = '10';
        document.getElementById('avatar_x_offset').value = '0';
        document.getElementById('avatar_y_offset').value = '0';
        document.getElementById('bar_y_offset').value = '0';
        document.getElementById('fps').value = '5';
        paused = false;
        updatePauseBtn();
        update();
    }

    function fetchPreview() {
        fetch('/api/frame')
            .then(r => r.json())
            .then(data => {
                document.getElementById('preview').textContent = data.frame;
                document.getElementById('preview').style.color = data.color || '#0f9';
            })
            .catch(() => {});
    }

    setInterval(fetchPreview, 200);
    fetchPreview();

    // Status hooks debug
    let rawJsonVisible = false;

    function toggleRawJson() {
        rawJsonVisible = !rawJsonVisible;
        document.getElementById('rawJson').style.display = rawJsonVisible ? 'block' : 'none';
    }

    function fetchStatus() {
        fetch('/api/status')
            .then(r => r.json())
            .then(data => {
                // Parsed status
                const parsed = data.parsed || {};
                const status = parsed.status || '--';
                document.getElementById('parsed_status').textContent = status;
                document.getElementById('parsed_status').className = 'status-value event-' + status;
                document.getElementById('parsed_color').textContent = parsed.color || '--';

                // Color swatch
                const colorMap = {green: '#0f9', yellow: '#ff0', blue: '#0af', red: '#f55', gray: '#888'};
                document.getElementById('color_swatch').style.background = colorMap[parsed.color] || '#333';

                document.getElementById('parsed_context').textContent =
                    parsed.context_percent != null ? parsed.context_percent.toFixed(1) + '%' : '--';
                document.getElementById('parsed_timestamp').textContent =
                    parsed.timestamp ? new Date(parsed.timestamp).toLocaleTimeString() : '--';

                // Raw hook event
                const raw = data.raw || {};
                document.getElementById('raw_event').textContent = raw.hook_event_name || '--';
                document.getElementById('raw_event').className = 'status-value event-' + (parsed.status || 'idle');
                document.getElementById('raw_session').textContent =
                    raw.session_id ? raw.session_id.substring(0, 8) + '...' : '--';
                document.getElementById('raw_model').textContent =
                    raw.model?.display_name || raw.model?.id || '--';
                document.getElementById('raw_cost').textContent =
                    raw.cost?.total_cost_usd != null ? '$' + raw.cost.total_cost_usd.toFixed(4) : '--';

                const ctx = raw.context_window || {};
                if (ctx.total_input_tokens) {
                    document.getElementById('raw_context_window').textContent =
                        (ctx.total_input_tokens + ctx.total_output_tokens).toLocaleString() + ' tokens';
                } else {
                    document.getElementById('raw_context_window').textContent = '--';
                }

                // Raw JSON
                document.getElementById('rawJson').textContent = JSON.stringify(raw, null, 2);
            })
            .catch(() => {});
    }

    setInterval(fetchStatus, 500);
    fetchStatus();
</script>
</body>
</html>
"""


class DebugHandler(SimpleHTTPRequestHandler):
    """HTTP request handler for debug UI."""

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode())
        elif self.path == "/api/frame":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            with lock:
                status, color, ctx = get_real_status()
                renderer.set_status(status)
                frame = renderer.render(ctx)
            color_map = {
                "idle": "#888", "resting": "#666", "thinking": "#ff0",
                "running": "#0f9", "executing": "#0f9", "awaiting": "#0af",
                "reading": "#0ff", "writing": "#0ff", "reviewing": "#f0f", "offline": "#444",
            }
            self.wfile.write(json.dumps({
                "frame": frame,
                "status": status,
                "color": color_map.get(status, "#0f9"),
            }).encode())
        elif self.path == "/api/config":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(config.to_dict()).encode())
        elif self.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()

            # Read raw hook data
            raw_data = {}
            if STATUS_RAW_FILE.exists():
                try:
                    raw_data = json.loads(STATUS_RAW_FILE.read_text())
                except (json.JSONDecodeError, IOError):
                    pass

            # Read parsed status from hub data
            parsed_data = {}
            try:
                hub_data = read_hub_data()
                parsed_data = hub_data.get("status", {})
            except:
                pass

            self.wfile.write(json.dumps({
                "raw": raw_data,
                "parsed": parsed_data,
            }).encode())
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/api/config":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                new_data = json.loads(body)
                with lock:
                    global config
                    for key, value in new_data.items():
                        if hasattr(config, key):
                            setattr(config, key, value)
                    config.save()
                    apply_config_to_renderer()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True}).encode())
            except Exception as e:
                self.send_error(400, str(e))
        else:
            self.send_error(404)


def get_real_status() -> tuple[str, str, float]:
    """Get status from config override or hub data. Returns (status, color, context_percent)."""
    if config.status_override:
        status = config.status_override
        color = "gray"
        ctx = config.context_percent_override if config.context_percent_override is not None else 50
    else:
        # Read from hub data (written by daemon)
        try:
            hub_data = read_hub_data()
            status_data = hub_data.get("status", {})
            status = status_data.get("status", "idle")
            color = status_data.get("color", "gray")
            ctx = status_data.get("context_percent") or 0
        except:
            status, color, ctx = "idle", "gray", 0

    # Allow context override even when using real status
    if config.context_percent_override is not None:
        ctx = config.context_percent_override

    return status, color, ctx


def get_real_weather() -> tuple[str, float]:
    """Get weather from config override or hub data. Returns (weather_type, intensity)."""
    # Check if config has "auto" or empty weather_type
    if config.weather_type and config.weather_type != "auto":
        return config.weather_type, config.weather_intensity

    # Read from hub data (written by daemon)
    try:
        hub_data = read_hub_data()
        weather_data = hub_data.get("weather", {})
        weather_type = weather_data.get("widget_type", "clear")
        intensity = weather_data.get("widget_intensity", 0.6)
        return weather_type, intensity
    except:
        return "clear", 0.6


def render_loop():
    """Background render loop - writes to widget display file."""
    global running
    output_file = Path("/tmp/widget-display.json")

    while running:
        with lock:
            if not config.paused:
                renderer.tick()
                status, color, ctx = get_real_status()
                renderer.set_status(status)
                frame = renderer.render(ctx)

                output = {
                    "frame": frame,
                    "status": status,
                    "color": color,
                    "context_percent": ctx,
                    "timestamp": time.time(),
                }

                try:
                    temp = output_file.with_suffix(".tmp")
                    temp.write_text(json.dumps(output))
                    temp.rename(output_file)
                except:
                    pass

            fps = config.fps

        time.sleep(1.0 / fps)


def main():
    global running, daemon_instance

    init_renderer()

    print("Starting Clarvis Debug UI...")
    print(f"Config file: {CONFIG_PATH}")
    print("Open http://localhost:8765 in your browser")
    print("Press Ctrl+C to stop\n")

    # Start status watcher daemon
    daemon_instance = CentralHubDaemon()
    daemon_instance.start_status_watcher()
    print("Status watcher started - monitoring hook events")

    render_thread = threading.Thread(target=render_loop, daemon=True)
    render_thread.start()

    server = HTTPServer(("localhost", 8765), DebugHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        running = False
        daemon_instance.stop_status_watcher()
        server.shutdown()


if __name__ == "__main__":
    main()
