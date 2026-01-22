# Composable Sprite System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a composable ASCII sprite system that allows multi-character shapes to be positioned, animated, and composited with procedural variation.

**Architecture:** Build on existing `CharacterGrid` and `DisplayComponent` infrastructure. Add `Sprite` (frame data), `SpriteInstance` (positioned/moving sprite), `SpriteSpawner` (automatic generation), and `SpriteLayer` (manages instances). Replace `WeatherBackground` with sprite-based weather.

**Tech Stack:** Swift, AppKit, existing CharacterGrid/DisplayCompositor

---

### Task 1: Sprite Struct (Core Data)

**Files:**
- Modify: `Display.swift` (add after `CharacterGrid` struct, ~line 234)

**Step 1: Write Sprite struct with ASCII parsing**

```swift
// MARK: - Sprite System

struct Sprite {
    let frames: [CharacterGrid]
    let anchor: (x: Int, y: Int)

    /// Create sprite from ASCII art strings (one per frame)
    /// Spaces are treated as transparent (nil in grid)
    init(frames: [String], transparent: Character = " ", anchor: (Int, Int) = (0, 0)) {
        self.frames = frames.map { Sprite.parseASCII($0, transparent: transparent) }
        self.anchor = anchor
    }

    /// Create sprite from pre-built grids
    init(grids: [CharacterGrid], anchor: (Int, Int) = (0, 0)) {
        self.frames = grids
        self.anchor = anchor
    }

    var width: Int { frames[0].width }
    var height: Int { frames[0].height }
    var frameCount: Int { frames.count }

    func frame(at index: Int) -> CharacterGrid {
        frames[index % frames.count]
    }

    private static func parseASCII(_ ascii: String, transparent: Character) -> CharacterGrid {
        let lines = ascii.split(separator: "\n", omittingEmptySubsequences: false).map { String($0) }
        let height = lines.count
        let width = lines.map { $0.count }.max() ?? 0

        var grid = CharacterGrid(width: width, height: height)
        for (y, line) in lines.enumerated() {
            for (x, char) in line.enumerated() {
                if char != transparent {
                    grid[x, y] = char
                }
            }
        }
        return grid
    }
}
```

**Step 2: Test manually by adding temporary test code**

Add at end of `applicationDidFinishLaunching`:
```swift
let testSprite = Sprite(frames: [" ** \n****\n ** "])
print("Sprite size: \(testSprite.width)x\(testSprite.height)")
print("Frame 0:\n\(testSprite.frame(at: 0).toString())")
```

**Step 3: Run to verify**

Run: `./restart.sh` or rebuild manually
Expected: Console shows sprite dimensions and ASCII output with transparency working

**Step 4: Remove test code and commit**

```bash
git add Display.swift
git commit -m "feat: add Sprite struct with ASCII parsing"
```

---

### Task 2: SpriteInstance Struct (Positioned Sprite)

**Files:**
- Modify: `Display.swift` (add after Sprite struct)

**Step 1: Write SpriteInstance struct**

```swift
struct SpriteInstance {
    let sprite: Sprite
    var x: Double
    var y: Double
    var velocityX: Double
    var velocityY: Double
    var currentFrame: Int
    var frameSpeed: Double  // Frames per update (0 = no animation)
    var frameAccumulator: Double
    var lifetime: Int  // -1 = infinite, 0 = dead, >0 = frames remaining

    init(sprite: Sprite, x: Double, y: Double,
         velocityX: Double = 0, velocityY: Double = 0,
         frameSpeed: Double = 0, lifetime: Int = -1) {
        self.sprite = sprite
        self.x = x
        self.y = y
        self.velocityX = velocityX
        self.velocityY = velocityY
        self.currentFrame = 0
        self.frameSpeed = frameSpeed
        self.frameAccumulator = 0
        self.lifetime = lifetime
    }

    var isDead: Bool { lifetime == 0 }

    mutating func update() {
        // Move
        x += velocityX
        y += velocityY

        // Animate frames
        if frameSpeed > 0 {
            frameAccumulator += frameSpeed
            while frameAccumulator >= 1 {
                currentFrame += 1
                frameAccumulator -= 1
            }
        }

        // Age
        if lifetime > 0 {
            lifetime -= 1
        }
    }

    func render() -> (grid: CharacterGrid, x: Int, y: Int) {
        let grid = sprite.frame(at: currentFrame)
        let renderX = Int(x) - sprite.anchor.x
        let renderY = Int(y) - sprite.anchor.y
        return (grid, renderX, renderY)
    }
}
```

**Step 2: Commit**

```bash
git add Display.swift
git commit -m "feat: add SpriteInstance for positioned/moving sprites"
```

---

### Task 3: SpriteSpawner Struct (Procedural Generation)

**Files:**
- Modify: `Display.swift` (add after SpriteInstance struct)

**Step 1: Write SpriteSpawner struct**

```swift
struct SpriteSpawner {
    let spriteVariants: [Sprite]  // Random selection for variation
    var spawnRate: Double  // Probability per update (0-1)
    var maxInstances: Int

    // Spawn ranges
    var xRange: ClosedRange<Double>
    var yRange: ClosedRange<Double>
    var velocityXRange: ClosedRange<Double>
    var velocityYRange: ClosedRange<Double>
    var frameSpeedRange: ClosedRange<Double>
    var lifetimeRange: ClosedRange<Int>

    init(spriteVariants: [Sprite],
         spawnRate: Double = 0.1,
         maxInstances: Int = 10,
         xRange: ClosedRange<Double>,
         yRange: ClosedRange<Double>,
         velocityXRange: ClosedRange<Double> = 0...0,
         velocityYRange: ClosedRange<Double> = 0...0,
         frameSpeedRange: ClosedRange<Double> = 0...0,
         lifetimeRange: ClosedRange<Int> = 50...150) {
        self.spriteVariants = spriteVariants
        self.spawnRate = spawnRate
        self.maxInstances = maxInstances
        self.xRange = xRange
        self.yRange = yRange
        self.velocityXRange = velocityXRange
        self.velocityYRange = velocityYRange
        self.frameSpeedRange = frameSpeedRange
        self.lifetimeRange = lifetimeRange
    }

    func shouldSpawn(currentCount: Int) -> Bool {
        currentCount < maxInstances && Double.random(in: 0...1) < spawnRate
    }

    func spawn() -> SpriteInstance {
        SpriteInstance(
            sprite: spriteVariants.randomElement()!,
            x: Double.random(in: xRange),
            y: Double.random(in: yRange),
            velocityX: Double.random(in: velocityXRange),
            velocityY: Double.random(in: velocityYRange),
            frameSpeed: Double.random(in: frameSpeedRange),
            lifetime: Int.random(in: lifetimeRange)
        )
    }
}
```

**Step 2: Commit**

```bash
git add Display.swift
git commit -m "feat: add SpriteSpawner for procedural sprite generation"
```

---

### Task 4: SpriteLayer DisplayComponent

**Files:**
- Modify: `Display.swift` (add after SpriteSpawner struct)

**Step 1: Write SpriteLayer class**

```swift
class SpriteLayer: DisplayComponent {
    var instances: [SpriteInstance] = []
    var spawners: [SpriteSpawner] = []

    var preferredSize: (width: Int, height: Int) { (0, 0) }  // Uses full grid

    func render(frame: Int, phase: Double, size: (width: Int, height: Int)) -> CharacterGrid {
        update(size: size)

        var grid = CharacterGrid(width: size.width, height: size.height)
        for instance in instances {
            let (spriteGrid, x, y) = instance.render()
            grid.composite(spriteGrid, at: (x, y))
        }
        return grid
    }

    private func update(size: (width: Int, height: Int)) {
        // Update existing instances, remove dead ones
        instances = instances.compactMap { instance in
            var i = instance
            i.update()

            // Remove if dead
            if i.isDead { return nil }

            // Remove if fully off-screen (with margin for sprite size)
            let margin = 5
            if i.x < Double(-margin) || i.x > Double(size.width + margin) ||
               i.y < Double(-margin) || i.y > Double(size.height + margin) {
                return nil
            }

            return i
        }

        // Run spawners
        for spawner in spawners {
            if spawner.shouldSpawn(currentCount: instances.count) {
                instances.append(spawner.spawn())
            }
        }
    }

    // Manual placement API
    func add(_ sprite: Sprite, at position: (x: Double, y: Double), velocity: (x: Double, y: Double) = (0, 0)) {
        instances.append(SpriteInstance(
            sprite: sprite,
            x: position.x,
            y: position.y,
            velocityX: velocity.x,
            velocityY: velocity.y,
            lifetime: -1
        ))
    }

    func clear() {
        instances.removeAll()
        spawners.removeAll()
    }
}
```

**Step 2: Commit**

```bash
git add Display.swift
git commit -m "feat: add SpriteLayer DisplayComponent"
```

---

### Task 5: SpriteCatalog (Predefined Shapes)

**Files:**
- Modify: `Display.swift` (add after SpriteLayer class)

**Step 1: Write SpriteCatalog with weather sprites**

```swift
struct SpriteCatalog {
    // MARK: - Clouds
    static let cloudTiny = Sprite(frames: ["∿∿"])

    static let cloudSmall = Sprite(frames: ["""
 ∿∿
∿∿∿∿
"""])

    static let cloudMedium = Sprite(frames: ["""
  ∿∿∿
 ∿∿∿∿∿
  ∿∿∿
"""])

    static let cloudLarge = Sprite(frames: ["""
   ∿∿∿∿
 ∿∿∿∿∿∿∿∿
  ∿∿∿∿∿∿
"""])

    // MARK: - Snow
    static let snowflake = Sprite(frames: ["*"])
    static let snowDot = Sprite(frames: ["·"])
    static let snowLarge = Sprite(frames: ["""
 *
***
 *
"""])

    // MARK: - Rain
    static let raindrop = Sprite(frames: ["│"])
    static let rainLight = Sprite(frames: [":"])
    static let rainStreak = Sprite(frames: ["""
│
│
"""])

    // MARK: - Fog
    static let fogDot = Sprite(frames: ["·"])
    static let fogWisp = Sprite(frames: ["···"])

    // MARK: - Decorations
    static let sparkle = Sprite(frames: ["·", "•", "✦", "•"])  // Animated
}
```

**Step 2: Commit**

```bash
git add Display.swift
git commit -m "feat: add SpriteCatalog with weather sprites"
```

---

### Task 6: Replace WeatherBackground with SpriteLayer

**Files:**
- Modify: `Display.swift`

**Step 1: Update StatusDisplayView to use SpriteLayer**

Replace the `weatherBackground` property and update compositor:

```swift
// In StatusDisplayView class, replace:
// private let weatherBackground = WeatherBackground()

// With:
private let backgroundLayer = SpriteLayer()
```

Update the `weatherType` setter to configure spawners:

```swift
var weatherType: WeatherType = .clear {
    didSet {
        configureWeather(weatherType)
        needsDisplay = true
    }
}

private func configureWeather(_ type: WeatherType) {
    backgroundLayer.clear()
    let w = Double(config.gridWidth)
    let h = Double(config.gridHeight)

    switch type {
    case .clear:
        break

    case .snow(let intensity):
        backgroundLayer.spawners.append(SpriteSpawner(
            spriteVariants: [SpriteCatalog.snowflake, SpriteCatalog.snowDot],
            spawnRate: intensity * 0.15,
            maxInstances: Int(intensity * Double(config.snowCount)),
            xRange: 0...w,
            yRange: -2...0,
            velocityXRange: -0.05...0.05,
            velocityYRange: 0.1...0.3,
            lifetimeRange: 40...100
        ))

    case .rain(let intensity):
        backgroundLayer.spawners.append(SpriteSpawner(
            spriteVariants: [SpriteCatalog.raindrop, SpriteCatalog.rainLight],
            spawnRate: intensity * 0.2,
            maxInstances: Int(intensity * Double(config.rainCount)),
            xRange: 0...w,
            yRange: -2...0,
            velocityXRange: -0.02...0.02,
            velocityYRange: 0.5...0.8,
            lifetimeRange: 20...60
        ))

    case .cloudy:
        backgroundLayer.spawners.append(SpriteSpawner(
            spriteVariants: [SpriteCatalog.cloudTiny, SpriteCatalog.cloudSmall, SpriteCatalog.cloudMedium],
            spawnRate: 0.02,
            maxInstances: config.cloudyCount / 3,  // Fewer but bigger
            xRange: 0...w,
            yRange: 0...h,
            velocityXRange: -0.03...0.03,
            velocityYRange: -0.02...0.02,
            lifetimeRange: 80...200
        ))

    case .fog:
        backgroundLayer.spawners.append(SpriteSpawner(
            spriteVariants: [SpriteCatalog.fogDot, SpriteCatalog.fogWisp],
            spawnRate: 0.1,
            maxInstances: config.fogCount,
            xRange: 0...w,
            yRange: 0...h,
            velocityXRange: -0.02...0.02,
            velocityYRange: -0.02...0.02,
            lifetimeRange: 60...150
        ))
    }
}
```

Update compositor layer:

```swift
// In compositor, replace weatherBackground with backgroundLayer:
ComponentLayer(component: backgroundLayer, zIndex: 0, origin: { _ in (0, 0) }),
```

**Step 2: Remove old WeatherBackground class**

Delete the entire `WeatherBackground` class and `Particle` struct (no longer needed).

**Step 3: Test**

Run: Rebuild and restart overlay
Expected: Weather effects work with new sprite-based system

**Step 4: Commit**

```bash
git add Display.swift
git commit -m "refactor: replace WeatherBackground with sprite-based SpriteLayer"
```

---

### Task 7: Update Control Panel for Sprite Parameters

**Files:**
- Modify: `control-panel.html`

**Step 1: Add sprite-specific controls**

Add to the Particle Counts section (or rename to "Sprite Settings"):

```html
<h2>Sprite Settings</h2>
<div class="control-group">
    <div class="row">
        <label>Cloud Max: <span class="value-display" id="cloudyCount-val">12</span></label>
        <input type="range" id="cloudyCount" min="2" max="20" value="12" step="1">
    </div>
    <div class="row">
        <label>Snow Max: <span class="value-display" id="snowCount-val">6</span></label>
        <input type="range" id="snowCount" min="2" max="30" value="6" step="1">
    </div>
    <!-- etc -->
</div>
```

**Step 2: Commit**

```bash
git add control-panel.html
git commit -m "feat: update control panel for sprite settings"
```

---

### Task 8: Final Integration Test

**Step 1: Full test**

1. Rebuild: `swiftc -o ClaudeStatusOverlay Display.swift ClaudeStatusOverlay.swift -framework Cocoa`
2. Start overlay: `./ClaudeStatusOverlay`
3. Start control server: `python3 control-server.py`
4. Test each weather type via control panel
5. Verify multi-character clouds render correctly
6. Verify MINUS operator still works (sprites don't show through avatar)

**Step 2: Final commit**

```bash
git add -A
git commit -m "feat: complete composable sprite system"
git push origin main
```

---

## Summary

| Task | Component | Purpose |
|------|-----------|---------|
| 1 | Sprite | Core data structure with ASCII parsing |
| 2 | SpriteInstance | Positioned, moving, animated sprite |
| 3 | SpriteSpawner | Procedural generation with variation |
| 4 | SpriteLayer | DisplayComponent managing instances |
| 5 | SpriteCatalog | Predefined sprite shapes |
| 6 | Integration | Replace WeatherBackground |
| 7 | Control Panel | UI updates |
| 8 | Testing | Full integration test |
