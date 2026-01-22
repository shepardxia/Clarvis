# Modular Display System Design

**Date:** 2026-01-22
**Goal:** Create a composable, layer-based display system that allows weather effects (snow, rain, etc.) to render behind the avatar.

---

## Overview

The current display renders components sequentially (avatar, then context bar). To support weather as an animated background, we need a **character grid compositing system** where multiple layers render to a shared grid, with proper transparency handling.

```
Layer 0 (back):  Weather particles (snow, rain, clouds)
Layer 1 (mid):   Avatar face
Layer 2 (front): Context bar

     Weather          Avatar          Composited
    *   *           ╭───────╮        ╭───────╮
      *       +     │ ●   ● │   =    │ ●   ● │
    *     *         │   ◡   │        │*  ◡  *│
        *           ╰───────╯        ╰───────╯
```

Snow particles appear where the avatar has empty space; the face remains solid.

---

## Core Abstractions

### CharacterGrid

A 2D array representing the display. Each cell is either a character or `nil` (transparent).

```swift
struct CharacterGrid {
    private(set) var cells: [[Character?]]
    let width: Int
    let height: Int

    init(width: Int, height: Int) {
        self.width = width
        self.height = height
        self.cells = Array(repeating: Array(repeating: nil, count: width), count: height)
    }

    subscript(x: Int, y: Int) -> Character? {
        get { cells[y][x] }
        set { cells[y][x] = newValue }
    }

    /// Composite another grid on top. Non-nil, non-space characters win.
    mutating func composite(_ other: CharacterGrid, at origin: (x: Int, y: Int)) {
        for y in 0..<other.height {
            for x in 0..<other.width {
                let destX = origin.x + x
                let destY = origin.y + y
                guard destX >= 0, destX < width, destY >= 0, destY < height else { continue }

                if let char = other[x, y], char != " " {
                    cells[destY][destX] = char
                }
            }
        }
    }

    /// Convert to renderable string
    func toString() -> String {
        cells.map { row in
            String(row.map { $0 ?? " " })
        }.joined(separator: "\n")
    }
}
```

### DisplayComponent Protocol

Each visual element implements this interface:

```swift
protocol DisplayComponent {
    /// Preferred size. Return (0, 0) to signal "fill available space".
    var preferredSize: (width: Int, height: Int) { get }

    /// Render one frame at the given size.
    /// - frame: Discrete animation step (for cycling states)
    /// - phase: Continuous time value (for smooth effects)
    /// - size: Actual render size (may differ from preferred)
    func render(frame: Int, phase: Double, size: (width: Int, height: Int)) -> CharacterGrid
}
```

### DisplayCompositor

Assembles components into layers and renders the final grid:

```swift
struct ComponentLayer {
    let component: DisplayComponent
    let zIndex: Int
    let origin: ((width: Int, height: Int)) -> (x: Int, y: Int)  // Dynamic positioning
}

class DisplayCompositor {
    var layers: [ComponentLayer] = []
    var gridSize: (width: Int, height: Int) = (11, 8)  // Configurable

    func render(frame: Int, phase: Double) -> CharacterGrid {
        var grid = CharacterGrid(width: gridSize.width, height: gridSize.height)

        for layer in layers.sorted(by: { $0.zIndex < $1.zIndex }) {
            let componentSize = layer.component.preferredSize
            let renderSize = componentSize == (0, 0) ? gridSize : componentSize
            let origin = layer.origin(gridSize)

            let componentGrid = layer.component.render(frame: frame, phase: phase, size: renderSize)
            grid.composite(componentGrid, at: origin)
        }

        return grid
    }
}
```

---

## Components

### WeatherBackground

Manages particles that animate across the full grid area.

```swift
enum WeatherType {
    case clear
    case snow(intensity: Double)      // 0.0 - 1.0
    case rain(intensity: Double)
    case cloudy
    case fog
}

struct Particle {
    var x: Double
    var y: Double
    var char: Character
    var speed: Double
    var drift: Double  // Horizontal movement per frame
}

class WeatherBackground: DisplayComponent {
    var weatherType: WeatherType = .clear
    private var particles: [Particle] = []

    var preferredSize: (width: Int, height: Int) { (0, 0) }  // Fill available

    func render(frame: Int, phase: Double, size: (width: Int, height: Int)) -> CharacterGrid {
        updateParticles(size: size)
        spawnParticles(size: size)
        return particlesToGrid(size: size)
    }

    private func updateParticles(size: (width: Int, height: Int)) {
        particles = particles.compactMap { p in
            var p = p
            p.y += p.speed
            p.x += p.drift

            // Remove if off screen
            guard p.y < Double(size.height) else { return nil }

            // Wrap horizontal
            if p.x < 0 { p.x += Double(size.width) }
            if p.x >= Double(size.width) { p.x -= Double(size.width) }

            return p
        }
    }

    private func spawnParticles(size: (width: Int, height: Int)) {
        switch weatherType {
        case .clear:
            break
        case .snow(let intensity):
            let spawnCount = Int(intensity * 2)  // 0-2 particles per frame
            for _ in 0..<spawnCount {
                if Double.random(in: 0...1) < intensity {
                    particles.append(Particle(
                        x: Double.random(in: 0..<Double(size.width)),
                        y: 0,
                        char: ["*", "·", "•"].randomElement()!,
                        speed: Double.random(in: 0.2...0.5),
                        drift: Double.random(in: -0.1...0.1)
                    ))
                }
            }
        case .rain(let intensity):
            let spawnCount = Int(intensity * 3)
            for _ in 0..<spawnCount {
                if Double.random(in: 0...1) < intensity {
                    particles.append(Particle(
                        x: Double.random(in: 0..<Double(size.width)),
                        y: 0,
                        char: ["|", "│", ":"].randomElement()!,
                        speed: Double.random(in: 0.8...1.2),
                        drift: 0
                    ))
                }
            }
        case .cloudy:
            // Clouds drift horizontally, don't fall
            if particles.count < 5 && Double.random(in: 0...1) < 0.1 {
                particles.append(Particle(
                    x: 0,
                    y: Double.random(in: 0..<Double(size.height / 2)),
                    char: ["~", "≈"].randomElement()!,
                    speed: 0,
                    drift: 0.1
                ))
            }
        case .fog:
            // Dense, slow random
            if particles.count < 15 && Double.random(in: 0...1) < 0.2 {
                particles.append(Particle(
                    x: Double.random(in: 0..<Double(size.width)),
                    y: Double.random(in: 0..<Double(size.height)),
                    char: ["·", "."].randomElement()!,
                    speed: Double.random(in: -0.05...0.05),
                    drift: Double.random(in: -0.05...0.05)
                ))
            }
        }
    }

    private func particlesToGrid(size: (width: Int, height: Int)) -> CharacterGrid {
        var grid = CharacterGrid(width: size.width, height: size.height)
        for p in particles {
            let x = Int(p.x)
            let y = Int(p.y)
            if x >= 0, x < size.width, y >= 0, y < size.height {
                grid[x, y] = p.char
            }
        }
        return grid
    }
}
```

**Weather type mapping** from JSON `description` field:

| JSON Description | WeatherType |
|-----------------|-------------|
| "Snow", "Light Snow", "Heavy Snow" | `.snow(intensity)` |
| "Rain", "Light Rain", "Heavy Rain", "Showers" | `.rain(intensity)` |
| "Overcast", "Cloudy", "Partly Cloudy" | `.cloudy` |
| "Foggy", "Fog" | `.fog` |
| "Clear", "Sunny" | `.clear` |

### AvatarFace

Refactored from existing `AvatarCache` logic. Renders the face to a grid instead of a string.

```swift
class AvatarFace: DisplayComponent {
    var status: String = "idle"

    var preferredSize: (width: Int, height: Int) { (11, 6) }

    func render(frame: Int, phase: Double, size: (width: Int, height: Int)) -> CharacterGrid {
        let frameString = AvatarCache.shared.frames(for: status)[frame % frameCount]
        return stringToGrid(frameString, size: size)
    }

    private func stringToGrid(_ string: String, size: (width: Int, height: Int)) -> CharacterGrid {
        var grid = CharacterGrid(width: size.width, height: size.height)
        let lines = string.components(separatedBy: "\n")
        for (y, line) in lines.enumerated() {
            for (x, char) in line.enumerated() {
                if x < size.width, y < size.height {
                    grid[x, y] = char
                }
            }
        }
        return grid
    }
}
```

### ContextBarComponent

Refactored from existing `ContextBar` logic.

```swift
class ContextBarComponent: DisplayComponent {
    var percent: Double = 0

    var preferredSize: (width: Int, height: Int) { (11, 1) }

    func render(frame: Int, phase: Double, size: (width: Int, height: Int)) -> CharacterGrid {
        let bar = ContextBar.render(percent: percent, width: size.width - 2)
        return stringToGrid(bar, size: size)
    }
}
```

---

## Integration

### StatusDisplayView (Revised)

```swift
class StatusDisplayView: NSView {
    // Data
    var status = ClaudeStatus()
    var weatherType: WeatherType = .clear

    // Components
    private let weatherBackground = WeatherBackground()
    private let avatarFace = AvatarFace()
    private let contextBar = ContextBarComponent()

    // Compositor
    private lazy var compositor: DisplayCompositor = {
        let c = DisplayCompositor()
        c.gridSize = (11, 8)
        c.layers = [
            ComponentLayer(component: weatherBackground, zIndex: 0, origin: { _ in (0, 0) }),
            ComponentLayer(component: avatarFace, zIndex: 1, origin: { size in
                (0, 1)  // 1 line from top
            }),
            ComponentLayer(component: contextBar, zIndex: 2, origin: { size in
                (0, size.height - 1)  // Bottom line
            }),
        ]
        return c
    }()

    // Animation
    private var frame: Int = 0
    private var phase: Double = 0

    override func draw(_ dirtyRect: NSRect) {
        // Update component data
        weatherBackground.weatherType = weatherType
        avatarFace.status = status.status
        contextBar.percent = status.contextPercent

        // Render
        let grid = compositor.render(frame: frame, phase: phase)

        // Draw
        drawBackground()
        drawGrid(grid)
        drawBorder()
    }

    private func drawGrid(_ grid: CharacterGrid) {
        let text = grid.toString()
        let color = status.isActive ? status.nsColor : NSColor(white: 0.7, alpha: 1)
        let attrs: [NSAttributedString.Key: Any] = [.foregroundColor: color, .font: font]

        // Calculate position and draw
        let lines = text.components(separatedBy: "\n")
        // ... positioning logic ...
    }
}
```

### WeatherWatcher (New)

Add to `ClaudeStatusOverlay.swift`:

```swift
class WeatherWatcher {
    private let weatherPath = "/tmp/central-hub-weather.json"
    private var source: DispatchSourceFileSystemObject?
    private var lastMod: Date?
    var onChange: ((WeatherType) -> Void)?

    func start() {
        // Same pattern as StatusWatcher
    }

    func readWeather() -> WeatherType {
        guard let data = FileManager.default.contents(atPath: weatherPath),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let description = json["description"] as? String else {
            return .clear
        }
        return mapDescriptionToWeatherType(description)
    }

    private func mapDescriptionToWeatherType(_ desc: String) -> WeatherType {
        let lower = desc.lowercased()
        if lower.contains("snow") {
            let intensity = lower.contains("heavy") ? 1.0 : lower.contains("light") ? 0.3 : 0.6
            return .snow(intensity: intensity)
        }
        if lower.contains("rain") || lower.contains("shower") || lower.contains("drizzle") {
            let intensity = lower.contains("heavy") ? 1.0 : lower.contains("light") ? 0.3 : 0.6
            return .rain(intensity: intensity)
        }
        if lower.contains("fog") { return .fog }
        if lower.contains("cloud") || lower.contains("overcast") { return .cloudy }
        return .clear
    }
}
```

---

## File Structure

```
central-hub/
├── Display.swift
│   ├── CharacterGrid
│   ├── DisplayComponent (protocol)
│   ├── DisplayCompositor
│   ├── WeatherBackground
│   ├── AvatarFace
│   ├── ContextBarComponent
│   ├── ClaudeStatus (existing)
│   └── StatusDisplayView (revised)
│
├── ClaudeStatusOverlay.swift
│   ├── StatusWatcher (existing)
│   ├── WeatherWatcher (new)
│   ├── AppDelegate (updated to wire weather)
│   └── @main
│
└── restart.sh (unchanged)
```

---

## Summary

| Concept | Purpose |
|---------|---------|
| `CharacterGrid` | 2D character buffer with transparency support |
| `DisplayComponent` | Interface for renderable elements |
| `DisplayCompositor` | Layers components back-to-front |
| `WeatherBackground` | Particle system for weather effects |
| `AvatarFace` | Existing avatar, refactored to grid output |
| `ContextBarComponent` | Existing bar, refactored to grid output |
| `WeatherWatcher` | Monitors weather JSON for changes |

**Key behaviors:**
- Snow/rain particles animate independently of avatar
- Particles appear in "empty" spaces (transparency compositing)
- Weather type derived from MCP server's weather description
- Grid size is configurable, not hardcoded
