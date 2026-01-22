#!/usr/bin/env python3
"""
Control Panel Server for Claude Status Overlay
Serves the control panel UI and handles config updates + restarts
"""

import json
import os
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

CONFIG_PATH = "/tmp/claude-overlay-config.json"
OVERLAY_DIR = Path(__file__).parent

class ControlHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/' or self.path == '/control-panel':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            with open(OVERLAY_DIR / 'control-panel.html', 'rb') as f:
                self.wfile.write(f.read())
        elif self.path.startswith('/tmp/'):
            # Serve JSON files from /tmp - convert /tmp/file to /tmp/file path
            filepath = Path('/' + self.path.lstrip('/'))
            if filepath.exists() and filepath.is_file():
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                with open(filepath, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "File not found"}')
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/save-config':
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)
            config = json.loads(body)

            # Save to file
            with open(CONFIG_PATH, 'w') as f:
                json.dump(config, f, indent=2)

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"success": true}')

        elif self.path == '/restart':
            try:
                # Kill and restart overlay
                subprocess.run(['pkill', '-f', 'ClaudeStatusOverlay'], stderr=subprocess.DEVNULL)
                subprocess.run(['rm', '-f', '/tmp/claude-status-overlay.lock'])

                import time
                time.sleep(0.5)

                # Rebuild and start
                os.chdir(OVERLAY_DIR)
                result = subprocess.run([
                    'swiftc', '-o', 'ClaudeStatusOverlay',
                    'Display.swift', 'ClaudeStatusOverlay.swift',
                    '-framework', 'Cocoa'
                ], capture_output=True, text=True)

                if result.returncode != 0:
                    print(f"Build error: {result.stderr}")
                    raise Exception(f"Build failed: {result.stderr}")

                # Start in background
                subprocess.Popen(
                    ['./ClaudeStatusOverlay'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )

                time.sleep(0.5)

                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"success": true}')
            except Exception as e:
                print(f"Restart error: {e}")
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Custom logging
        print(f"[Control Panel] {args[0]}")

if __name__ == '__main__':
    port = 8765
    server = HTTPServer(('localhost', port), ControlHandler)
    print(f"🎛️  Control Panel: http://localhost:{port}")
    print(f"📝 Config file: {CONFIG_PATH}")
    server.serve_forever()
