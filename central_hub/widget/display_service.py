"""
Display service - renders widget frames from processed server data.

Reads status/weather from central hub, generates ASCII frames, writes to widget output.
Runs at ~10fps.
"""

import json
import time
import threading
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from .renderer import FrameRenderer

# File paths
HUB_DATA_FILE = Path("/tmp/central-hub-data.json")     # Input: processed data from server
OUTPUT_FILE = Path("/tmp/widget-display.json")         # Output: rendered frames + metadata

# Border styles by status
BORDER_STYLES = {
    "running": {"width": 3, "pulse": True},
    "thinking": {"width": 3, "pulse": True},
    "awaiting": {"width": 2, "pulse": True},
    "resting": {"width": 1, "pulse": False},
    "idle": {"width": 1, "pulse": False},
    "offline": {"width": 1, "pulse": False},
}


class DisplayService:
    """Renders widget frames from processed server data."""

    def __init__(self):
        self.renderer = FrameRenderer()
        self.status = "idle"
        self.color = "gray"
        self.context_percent = 0.0
        self.weather_type = "clear"
        self.weather_intensity = 0.0
        self.running = False
        self.lock = threading.Lock()

    def read_data(self):
        """Read processed status and weather from server."""
        if not HUB_DATA_FILE.exists():
            return

        try:
            data = json.loads(HUB_DATA_FILE.read_text())

            # Extract processed status
            status_data = data.get("status", {})
            status = status_data.get("status", "idle")
            color = status_data.get("color", "gray")
            context_percent = status_data.get("context_percent", 0)

            # Extract weather
            weather_data = data.get("weather", {})
            description = weather_data.get("description", "").lower()

            # Map description to weather type and intensity
            weather_type = "clear"
            intensity = 0.6

            if "snow" in description:
                weather_type = "snow"
                intensity = 1.0 if "heavy" in description else 0.3 if "light" in description else 0.6
            elif "rain" in description or "shower" in description or "drizzle" in description:
                weather_type = "rain"
                intensity = 1.0 if "heavy" in description else 0.3 if "light" in description else 0.6
            elif "fog" in description:
                weather_type = "fog"
            elif "cloud" in description or "overcast" in description:
                weather_type = "cloudy"

            with self.lock:
                self.status = status
                self.color = color
                self.context_percent = context_percent or 0
                self.renderer.set_status(self.status)

                if weather_type != self.weather_type or intensity != self.weather_intensity:
                    self.weather_type = weather_type
                    self.weather_intensity = intensity
                    self.renderer.set_weather(weather_type, intensity)

        except (json.JSONDecodeError, IOError):
            pass

    def write_output(self):
        """Write rendered frame to output JSON."""
        with self.lock:
            frame = self.renderer.render(self.context_percent)
            border = BORDER_STYLES.get(self.status, {"width": 1, "pulse": False})

            # Single output: status + rendered frame
            output = {
                "frame": frame,
                "color": self.color,
                "status": self.status,
                "border_width": border["width"],
                "border_pulse": border["pulse"],
                "context_percent": self.context_percent,
                "timestamp": time.time(),
            }

        # Atomic write
        temp_file = OUTPUT_FILE.with_suffix(".tmp")
        temp_file.write_text(json.dumps(output))
        temp_file.rename(OUTPUT_FILE)

    def tick(self):
        """Advance animation and write frame."""
        with self.lock:
            self.renderer.tick()
        self.write_output()

    def run(self, fps: int = 10):  # pragma: no cover
        """Main loop - run at specified FPS."""
        self.running = True
        interval = 1.0 / fps

        # Initial read
        self.read_data()

        # Set up file watcher
        class DataHandler(FileSystemEventHandler):
            def __init__(self, service):
                self.service = service

            def on_modified(self, event):
                if event.src_path == str(HUB_DATA_FILE):
                    self.service.read_data()

        observer = Observer()
        handler = DataHandler(self)
        observer.schedule(handler, str(HUB_DATA_FILE.parent), recursive=False)
        observer.start()

        print(f"Display service running at {fps} FPS")
        print(f"Input: {HUB_DATA_FILE}")
        print(f"Output: {OUTPUT_FILE}")

        try:
            while self.running:
                start = time.time()
                self.tick()
                elapsed = time.time() - start
                sleep_time = max(0, interval - elapsed)
                time.sleep(sleep_time)
        except KeyboardInterrupt:
            print("\nStopping...")
        finally:
            observer.stop()
            observer.join()

    def stop(self):  # pragma: no cover
        """Stop the service."""
        self.running = False


def main():  # pragma: no cover
    """Entry point."""
    service = DisplayService()
    service.run(fps=2)


if __name__ == "__main__":  # pragma: no cover
    main()
