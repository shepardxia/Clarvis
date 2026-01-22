import Cocoa
import Foundation

// MARK: - Config Model

struct OverlayConfig: Codable {
    var gridWidth: Int = 14
    var gridHeight: Int = 10
    var fontSize: Int = 20
    var avatarX: Int = 2
    var avatarY: Int = 2
    var barX: Int = 2
    var barY: Int = 8
    var snowCount: Int = 6
    var rainCount: Int = 8
    var cloudyCount: Int = 12
    var fogCount: Int = 20

    static func load() -> OverlayConfig {
        let path = "/tmp/claude-overlay-config.json"
        guard let data = FileManager.default.contents(atPath: path),
              let config = try? JSONDecoder().decode(OverlayConfig.self, from: data) else {
            return OverlayConfig()
        }
        return config
    }
}

// MARK: - Status Model

struct ClaudeStatus: Equatable {
    var status: String = "idle"
    var tool: String = ""
    var color: String = "gray"
    var text: String = "Starting..."
    var contextPercent: Double = 0

    var nsColor: NSColor {
        switch color {
        case "green": return NSColor(red: 0.133, green: 0.773, blue: 0.369, alpha: 1)
        case "yellow": return NSColor(red: 0.918, green: 0.702, blue: 0.031, alpha: 1)
        case "blue": return NSColor(red: 0.231, green: 0.510, blue: 0.965, alpha: 1)
        default: return NSColor(red: 0.580, green: 0.580, blue: 0.580, alpha: 1)
        }
    }

    var isActive: Bool {
        ["running", "thinking", "awaiting", "resting", "reading", "writing", "executing", "reviewing"].contains(status)
    }
}

// MARK: - Avatar Components

struct AvatarComponents {

    static func border(for status: String) -> String {
        switch status {
        case "working", "running", "executing": return "═"
        case "thinking", "reviewing": return "~"
        case "awaiting": return "⋯"
        case "reading": return "·"
        case "writing": return "▪"
        case "offline": return "·"
        default: return "─"
        }
    }

    static let eyes: [String: [String]] = [
        "idle": ["·"],
        "resting": ["·"],
        "thinking": ["˘"],
        "working": ["●"],
        "awaiting": ["?"],
        "offline": ["·"],
        "reading": ["◦"],
        "writing": ["●"],
        "executing": ["●"],
        "reviewing": ["˘"]
    ]

    // Eye positions for 9-char interior: (left, gap, right) must sum to 7
    static let eyePositions: [String: [(Int, Int, Int)]] = [
        "idle": [(3,1,3)],
        "resting": [(3,1,3)],
        "thinking": [(3,1,3), (4,1,2), (3,1,3), (2,1,4)],
        "working": [(3,1,3)],
        "awaiting": [(3,1,3), (4,1,2), (3,1,3), (2,1,4)],
        "offline": [(3,1,3)],
        "reading": [(3,1,3), (4,1,2), (3,1,3), (2,1,4)],
        "writing": [(3,1,3)],
        "executing": [(3,1,3)],
        "reviewing": [(3,1,3), (4,1,2), (3,1,3), (2,1,4)]
    ]

    static let mouths: [String: String] = [
        "idle": "◡",
        "resting": "◡",
        "thinking": "~",
        "working": "◡",
        "awaiting": "·",
        "offline": "─",
        "reading": "○",
        "writing": "◡",
        "executing": "▬",
        "reviewing": "~"
    ]

    static let substrates: [String: [String]] = [
        "idle": [" ·  ·  · "],
        "resting": [" ·  ·  · ", "·  ·  ·  ", " ·  ·  · ", "  ·  ·  ·"],
        "thinking": [" • ◦ • ◦ ", " ◦ • ◦ • "],
        "working": [" • ● • ● ", " ● • ● • "],
        "awaiting": [" · · · · ", "· · · ·  ", " · · · · ", "  · · · ·"],
        "offline": ["  · · ·  "],
        "reading": [" ▸ · · · ", " · ▸ · · ", " · · ▸ · ", " · · · ▸ "],
        "writing": [" ▪ ▪ ▪ ▪ ", " ▫ ▪ ▪ ▪ ", " ▫ ▫ ▪ ▪ ", " ▫ ▫ ▫ ▪ "],
        "executing": [" ▶ ▶ ▶ ▶ ", " ▷ ▶ ▶ ▶ ", " ▷ ▷ ▶ ▶ ", " ▷ ▷ ▷ ▶ "],
        "reviewing": [" ◇ ◇ ◇ ◇ ", " ◆ ◇ ◇ ◇ ", " ◆ ◆ ◇ ◇ ", " ◆ ◆ ◆ ◇ "]
    ]
}

// MARK: - Avatar Cache

class AvatarCache {
    static let shared = AvatarCache()
    private var cache: [String: [String]] = [:]

    func frames(for status: String) -> [String] {
        if let cached = cache[status] { return cached }

        let border = AvatarComponents.border(for: status)
        let eye = AvatarComponents.eyes[status]?.first ?? "·"
        let positions = AvatarComponents.eyePositions[status] ?? [(2,3,2)]
        let mouth = AvatarComponents.mouths[status] ?? "◡"
        let subs = AvatarComponents.substrates[status] ?? ["  · · ·  "]

        let frameCount = max(positions.count, subs.count)
        var frames: [String] = []

        for i in 0..<frameCount {
            let pos = positions[i % positions.count]
            let sub = subs[i % subs.count]
            frames.append(buildFrame(border: border, eye: eye, pos: pos, mouth: mouth, sub: sub))
        }

        cache[status] = frames
        return frames
    }

    // Larger 11x5 avatar frame
    private func buildFrame(border: String, eye: String, pos: (Int,Int,Int), mouth: String, sub: String) -> String {
        let (l, g, r) = pos
        return """
        ╭\(String(repeating: border, count: 9))╮
        |\(String(repeating: " ", count: l))\(eye)\(String(repeating: " ", count: g))\(eye)\(String(repeating: " ", count: r))|
        |    \(mouth)    |
        |\(sub)|
        ╰\(String(repeating: border, count: 9))╯
        """
    }
}

// MARK: - Context Bar

struct ContextBar {
    // Horizontal bar (legacy)
    static func render(percent: Double, width: Int = 9) -> String {
        let filled = Int((percent / 100.0) * Double(width))
        return " \(String(repeating: "█", count: filled))\(String(repeating: "░", count: width - filled)) "
    }

    // Vertical bar - returns array of rows (bottom to top fill)
    static func renderVertical(percent: Double, height: Int = 5) -> [String] {
        let filled = Int((percent / 100.0) * Double(height))
        var rows: [String] = []
        for i in 0..<height {
            // Fill from bottom: row 0 is top, row height-1 is bottom
            let rowFromBottom = height - 1 - i
            rows.append(rowFromBottom < filled ? "█" : "░")
        }
        return rows
    }
}

// MARK: - Modular Display System

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

    /// MINUS operator: clears this grid where another grid's bounds cover
    /// Used to cut out regions so weather doesn't show through solid components
    mutating func subtract(_ other: CharacterGrid, at origin: (x: Int, y: Int)) {
        for y in 0..<other.height {
            for x in 0..<other.width {
                let destX = origin.x + x
                let destY = origin.y + y
                guard destX >= 0, destX < width, destY >= 0, destY < height else { continue }
                cells[destY][destX] = nil
            }
        }
    }

    func toString() -> String {
        cells.map { row in
            String(row.map { $0 ?? " " })
        }.joined(separator: "\n")
    }
}

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

protocol DisplayComponent {
    var preferredSize: (width: Int, height: Int) { get }
    func render(frame: Int, phase: Double, size: (width: Int, height: Int)) -> CharacterGrid
}

struct ComponentLayer {
    let component: DisplayComponent
    let zIndex: Int
    let origin: ((width: Int, height: Int)) -> (x: Int, y: Int)
    let subtractsBelow: Bool  // MINUS operator: clears underlying layers in this component's bounds

    init(component: DisplayComponent, zIndex: Int, origin: @escaping ((width: Int, height: Int)) -> (x: Int, y: Int), subtractsBelow: Bool = false) {
        self.component = component
        self.zIndex = zIndex
        self.origin = origin
        self.subtractsBelow = subtractsBelow
    }
}

class DisplayCompositor {
    var layers: [ComponentLayer] = []
    var gridSize: (width: Int, height: Int) = (11, 8)

    func render(frame: Int, phase: Double) -> CharacterGrid {
        var grid = CharacterGrid(width: gridSize.width, height: gridSize.height)
        for layer in layers.sorted(by: { $0.zIndex < $1.zIndex }) {
            let componentSize = layer.component.preferredSize
            let renderSize = componentSize == (0, 0) ? gridSize : componentSize
            let origin = layer.origin(gridSize)
            let componentGrid = layer.component.render(frame: frame, phase: phase, size: renderSize)

            // MINUS operator: subtract this component's bounds from underlying layers
            if layer.subtractsBelow {
                grid.subtract(componentGrid, at: origin)
            }

            grid.composite(componentGrid, at: origin)
        }
        return grid
    }
}

enum WeatherType {
    case clear
    case snow(intensity: Double)
    case rain(intensity: Double)
    case cloudy
    case fog
}

struct Particle {
    var x: Double
    var y: Double
    var char: Character
    var speed: Double
    var drift: Double
    var lifetime: Int  // frames until respawn
}

class WeatherBackground: DisplayComponent {
    var weatherType: WeatherType = .clear
    var config: OverlayConfig = OverlayConfig.load()
    private var particles: [Particle] = []

    var preferredSize: (width: Int, height: Int) { (0, 0) }

    func render(frame: Int, phase: Double, size: (width: Int, height: Int)) -> CharacterGrid {
        updateParticles(size: size)
        spawnParticles(size: size)
        return particlesToGrid(size: size)
    }

    private func updateParticles(size: (width: Int, height: Int)) {
        particles = particles.map { p in
            var p = p
            p.lifetime -= 1
            p.y += p.speed
            p.x += p.drift
            // Respawn if expired or off-screen
            if p.lifetime <= 0 || p.y >= Double(size.height) || p.y < 0 {
                p.x = Double.random(in: 0..<Double(size.width))
                p.y = Double.random(in: 0..<Double(size.height))
                p.lifetime = Int.random(in: 30...90)
            }
            // Wrap horizontally
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
            let targetCount = Int(intensity * Double(config.snowCount))
            while particles.count < targetCount {
                particles.append(Particle(
                    x: Double.random(in: 0..<Double(size.width)),
                    y: Double.random(in: 0..<Double(size.height)),
                    char: ["*", "·", "•"].randomElement()!,
                    speed: Double.random(in: 0.1...0.3),
                    drift: Double.random(in: -0.05...0.05),
                    lifetime: Int.random(in: 40...100)
                ))
            }
        case .rain(let intensity):
            let targetCount = Int(intensity * Double(config.rainCount))
            while particles.count < targetCount {
                particles.append(Particle(
                    x: Double.random(in: 0..<Double(size.width)),
                    y: Double.random(in: 0..<Double(size.height)),
                    char: ["|", "│", ":"].randomElement()!,
                    speed: Double.random(in: 0.5...0.8),
                    drift: Double.random(in: -0.02...0.02),
                    lifetime: Int.random(in: 20...60)
                ))
            }
        case .cloudy:
            let targetCount = config.cloudyCount
            while particles.count < targetCount {
                particles.append(Particle(
                    x: Double.random(in: 0..<Double(size.width)),
                    y: Double.random(in: 0..<Double(size.height)),
                    char: ["~", "≈", "∼"].randomElement()!,
                    speed: Double.random(in: -0.02...0.02),
                    drift: Double.random(in: -0.03...0.03),
                    lifetime: Int.random(in: 50...120)
                ))
            }
        case .fog:
            let targetCount = config.fogCount
            while particles.count < targetCount {
                particles.append(Particle(
                    x: Double.random(in: 0..<Double(size.width)),
                    y: Double.random(in: 0..<Double(size.height)),
                    char: ["·", ".", "˙"].randomElement()!,
                    speed: Double.random(in: -0.02...0.02),
                    drift: Double.random(in: -0.02...0.02),
                    lifetime: Int.random(in: 60...150)
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

class AvatarFace: DisplayComponent {
    var status: String = "idle"

    var preferredSize: (width: Int, height: Int) { (11, 5) }

    func render(frame: Int, phase: Double, size: (width: Int, height: Int)) -> CharacterGrid {
        let frames = AvatarCache.shared.frames(for: status)
        let frameString = frames[frame % frames.count]
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

class ContextBarComponent: DisplayComponent {
    var percent: Double = 0

    var preferredSize: (width: Int, height: Int) { (9, 1) }

    func render(frame: Int, phase: Double, size: (width: Int, height: Int)) -> CharacterGrid {
        var grid = CharacterGrid(width: size.width, height: size.height)
        let bar = ContextBar.render(percent: percent, width: size.width)
        for (x, char) in bar.enumerated() {
            if x < size.width {
                grid[x, 0] = char
            }
        }
        return grid
    }
}

// MARK: - Display View

class StatusDisplayView: NSView {
    var status = ClaudeStatus() {
        didSet {
            if oldValue.status != status.status { currentFrame = 0 }
            updateAnimationState()
            needsDisplay = true
        }
    }

    var weatherType: WeatherType = .clear {
        didSet { needsDisplay = true }
    }

    private var config = OverlayConfig.load()
    private var pulsePhase: CGFloat = 0
    private var currentFrame: Int = 0
    private var pulseTimer: Timer?
    private var frameTimer: Timer?
    private var font: NSFont { NSFont.monospacedSystemFont(ofSize: CGFloat(config.fontSize), weight: .regular) }

    private let weatherBackground = WeatherBackground()
    private let avatarFace = AvatarFace()
    private let contextBarComponent = ContextBarComponent()

    private lazy var compositor: DisplayCompositor = {
        let c = DisplayCompositor()
        c.gridSize = (self.config.gridWidth, self.config.gridHeight)
        c.layers = [
            ComponentLayer(component: self.weatherBackground, zIndex: 0, origin: { _ in (0, 0) }),
            ComponentLayer(component: self.avatarFace, zIndex: 1, origin: { _ in (self.config.avatarX, self.config.avatarY) }, subtractsBelow: true),
            ComponentLayer(component: self.contextBarComponent, zIndex: 2, origin: { _ in (self.config.barX, self.config.barY) }, subtractsBelow: true),
        ]
        return c
    }()

    override init(frame: NSRect) {
        super.init(frame: frame)
        updateAnimationState()
    }

    required init?(coder: NSCoder) { super.init(coder: coder) }

    private func updateAnimationState() {
        status.isActive ? startAnimations() : stopAnimations()
    }

    private func startAnimations() {
        if pulseTimer == nil {
            pulseTimer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
                self?.pulsePhase += 0.1
                self?.needsDisplay = true
            }
        }
        if frameTimer == nil {
            frameTimer = Timer.scheduledTimer(withTimeInterval: 0.4, repeats: true) { [weak self] _ in
                guard let self = self else { return }
                let frames = AvatarCache.shared.frames(for: self.status.status)
                self.currentFrame = (self.currentFrame + 1) % frames.count
                self.needsDisplay = true
            }
        }
    }

    private func stopAnimations() {
        pulseTimer?.invalidate()
        pulseTimer = nil
        frameTimer?.invalidate()
        frameTimer = nil
    }

    override func draw(_ dirtyRect: NSRect) {
        // Update component data
        weatherBackground.weatherType = weatherType
        avatarFace.status = status.status
        contextBarComponent.percent = status.contextPercent

        // Render composited grid
        let grid = compositor.render(frame: currentFrame, phase: pulsePhase)
        let displayText = grid.toString()

        drawBackground()
        drawBorder()
        drawComposited(displayText)
    }

    private func drawBackground() {
        let bg = NSBezierPath(roundedRect: bounds, xRadius: 10, yRadius: 10)
        NSColor(white: 0, alpha: 0.6).setFill()
        bg.fill()
    }

    private func drawBorder() {
        let (alpha, width): (CGFloat, CGFloat) = borderStyle(for: status.status)
        let bg = NSBezierPath(roundedRect: bounds, xRadius: 10, yRadius: 10)
        status.nsColor.withAlphaComponent(alpha).setStroke()
        bg.lineWidth = width
        bg.stroke()
    }

    private func borderStyle(for status: String) -> (CGFloat, CGFloat) {
        switch status {
        case "running": return (0.5 + 0.3 * sin(pulsePhase * 4), 3)
        case "thinking": return (0.4 + 0.2 * sin(pulsePhase * 2), 3)
        case "awaiting": return (0.4 + 0.2 * sin(pulsePhase * 1.5), 2)
        case "resting": return (0.2 + 0.1 * sin(pulsePhase * 0.5), 1)
        case "idle": return (0.15, 1)
        default: return (0.1, 1)
        }
    }

    private func drawComposited(_ text: String) {
        let color = status.isActive ? status.nsColor : NSColor(white: 0.7, alpha: 1)
        let attrs: [NSAttributedString.Key: Any] = [.foregroundColor: color, .font: font]

        let lineH = font.ascender - font.descender + font.leading
        let lines = text.components(separatedBy: "\n")
        let textH = CGFloat(lines.count) * lineH
        let textW = lines.first?.size(withAttributes: attrs).width ?? 0

        let x = (bounds.width - textW) / 2
        let y = (bounds.height - textH) / 2

        text.draw(at: NSPoint(x: x, y: y), withAttributes: attrs)
    }
}
