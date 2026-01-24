#!/usr/bin/env python3
"""Clarvis Widget - Minimal, configurable launcher."""

import tkinter as tk
from tkinter import font as tkfont
import math
from clarvis.widget.renderer import FrameRenderer

# macOS native window control
try:
    from AppKit import (
        NSApp,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorStationary,
        NSWindowCollectionBehaviorFullScreenAuxiliary,
    )
    from Quartz import kCGMaximumWindowLevelKey, CGWindowLevelForKey
    HAS_APPKIT = True
except ImportError:
    HAS_APPKIT = False


# =============================================================================
# Configuration
# =============================================================================

CONFIG = {
    "scale": 1.8,
    "shape": "rounded",  # "circle", "rounded", "square"
    "bg_color": "#0d0d14",
    "bg_alpha": 0.75,
    "border_radius": 40,  # for "rounded" shape - very rounded
    "border_width": 2,
    "font_family": "Menlo",
    "font_size": 12,  # smaller font
    "padding": 20,
    "status_cycle_ms": 4000,
    "animation_fps": 5,
    "pulse_speed": 0.1,
}

STATUS_COLORS = {
    "idle": "#888899",
    "thinking": "#ffdd00",
    "running": "#00ffaa",
    "awaiting": "#00ccff",
    "resting": "#666688",
}


# =============================================================================
# Widget
# =============================================================================

class ClarvisWidget:
    def __init__(self, config=None):
        self.cfg = {**CONFIG, **(config or {})}

        self.root = tk.Tk()
        self.root.title('Clarvis')
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)

        # macOS: use systemTransparent for per-pixel transparency
        if self.cfg["shape"] in ("circle", "rounded"):
            self.root.attributes('-transparent', True)
            self.root.attributes('-alpha', self.cfg["bg_alpha"])
            self.root.config(bg='systemTransparent')
            self._use_transparent_bg = True
        else:
            self.root.attributes('-alpha', self.cfg["bg_alpha"])
            self.root.configure(bg=self.cfg["bg_color"])
            self._use_transparent_bg = False

        scale = self.cfg["scale"]
        pad = self.cfg["padding"]
        shape = self.cfg["shape"]

        # Calculate size based on content
        self.font = tkfont.Font(family=self.cfg["font_family"],
                                size=int(self.cfg["font_size"] * scale),
                                weight='bold')

        # Size depends on shape
        if shape == "circle":
            size = int(220 * scale)
            w, h = size, size
        else:
            w = int(220 * scale)
            h = int(180 * scale)
        self.w, self.h = w, h

        # Canvas background
        if self._use_transparent_bg:
            canvas_bg = 'systemTransparent'
        else:
            canvas_bg = self.cfg["bg_color"]

        self.canvas = tk.Canvas(self.root, width=w, height=h,
                                bg=canvas_bg, highlightthickness=0)
        self.canvas.pack()

        # Draw border based on shape
        bw = self.cfg["border_width"]
        if shape == "circle":
            # Fill the circle with background color (only visible part)
            self.canvas.create_oval(
                pad, pad, w - pad, h - pad,
                fill=self.cfg["bg_color"], outline=''
            )
            # Border on top
            self.border = self.canvas.create_oval(
                pad, pad, w - pad, h - pad,
                fill='', outline='#888899', width=bw
            )
        elif shape == "rounded":
            r = self.cfg["border_radius"]
            # Fill with background color first
            self._rounded_rect(pad//2, pad//2, w - pad, h - pad, r,
                               fill=self.cfg["bg_color"], outline='')
            # Border on top
            self.border = self._rounded_rect(pad//2, pad//2, w - pad, h - pad, r,
                                             fill='', outline='#888899', width=bw)
        else:  # square
            self.border = self.canvas.create_rectangle(
                pad, pad, w - pad, h - pad,
                fill='', outline='#888899', width=bw
            )

        # Face display
        self.display = self.canvas.create_text(
            w // 2, h // 2,
            text='',
            font=self.font,
            fill='#888899',
            justify='center'
        )

        # Renderer
        self.renderer = FrameRenderer(width=14, height=8)
        self.statuses = list(STATUS_COLORS.keys())
        self.idx = 0
        self.phase = 0
        self.ctx = 30

        # Bindings
        self.canvas.bind('<Button-1>', self._start_drag)
        self.canvas.bind('<B1-Motion>', self._drag)
        self.canvas.bind('<Button-3>', lambda e: self.root.destroy())
        self.root.bind('<Escape>', lambda e: self.root.destroy())
        self.canvas.bind('<Double-Button-1>', lambda e: self._cycle())

        # Position top-right
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        self.root.geometry(f'+{screen_w - w - 40}+40')

        self.dx, self.dy = 0, 0

        # Start loops
        self._animate()
        self._pulse()
        self.root.after(100, self._set_native_float)  # Set after window visible
        self._stay_on_top()
        self.root.after(self.cfg["status_cycle_ms"], self._auto_cycle)

    def _rounded_rect(self, x, y, w, h, r, **kw):
        pts = [x+r, y, x+w-r, y, x+w, y, x+w, y+r, x+w, y+h-r, x+w, y+h,
               x+w-r, y+h, x+r, y+h, x, y+h, x, y+h-r, x, y+r, x, y]
        return self.canvas.create_polygon(pts, smooth=True, **kw)

    def _start_drag(self, e):
        self.dx, self.dy = e.x, e.y

    def _drag(self, e):
        x = self.root.winfo_x() + e.x - self.dx
        y = self.root.winfo_y() + e.y - self.dy
        self.root.geometry(f'+{x}+{y}')

    def _animate(self):
        self.renderer.tick()
        frame = self.renderer.render(context_percent=self.ctx)
        self.canvas.itemconfig(self.display, text=frame)
        self.ctx = (self.ctx + 0.3) % 100

        interval = 1000 // self.cfg["animation_fps"]
        self.root.after(interval, self._animate)

    def _set_native_float(self):
        """Set native macOS floating window - visible on all spaces including fullscreen."""
        if HAS_APPKIT:
            self.root.update_idletasks()
            # Get maximum window level to appear above fullscreen
            max_level = CGWindowLevelForKey(kCGMaximumWindowLevelKey)
            for window in NSApp.windows():
                window.setLevel_(max_level)
                # Visible on all spaces + stationary + works with fullscreen
                behavior = (
                    NSWindowCollectionBehaviorCanJoinAllSpaces |
                    NSWindowCollectionBehaviorStationary |
                    NSWindowCollectionBehaviorFullScreenAuxiliary
                )
                window.setCollectionBehavior_(behavior)

    def _stay_on_top(self):
        """Periodically enforce staying on top."""
        if HAS_APPKIT:
            max_level = CGWindowLevelForKey(kCGMaximumWindowLevelKey)
            for window in NSApp.windows():
                window.setLevel_(max_level)
        self.root.lift()
        self.root.after(1000, self._stay_on_top)

    def _pulse(self):
        self.phase += self.cfg["pulse_speed"]
        t = (math.sin(self.phase) + 1) / 2  # 0 to 1

        color = STATUS_COLORS[self.statuses[self.idx]]
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)

        # Interpolate brightness
        factor = 0.4 + 0.6 * t
        pr = min(255, int(r * factor))
        pg = min(255, int(g * factor))
        pb = min(255, int(b * factor))
        pulse_color = f'#{pr:02x}{pg:02x}{pb:02x}'

        self.canvas.itemconfig(self.border, outline=pulse_color)
        self.root.after(40, self._pulse)

    def _cycle(self):
        self.idx = (self.idx + 1) % len(self.statuses)
        status = self.statuses[self.idx]
        self.renderer.set_status(status)
        self.canvas.itemconfig(self.display, fill=STATUS_COLORS[status])

    def _auto_cycle(self):
        self._cycle()
        self.root.after(self.cfg["status_cycle_ms"], self._auto_cycle)

    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    ClarvisWidget().run()
