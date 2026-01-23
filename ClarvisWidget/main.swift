import Cocoa
import Foundation

// MARK: - Configuration

struct Config {
    static let jsonPath = "/tmp/widget-display.json"
    static let pollInterval: TimeInterval = 0.2
    static let windowSize = NSSize(width: 280, height: 220)
    static let cornerRadius: CGFloat = 24
    static let bgAlpha: CGFloat = 0.75
    static let fontSize: CGFloat = 14
    static let borderWidth: CGFloat = 2
    static let pulseSpeed: Double = 0.1

    static let statusColors: [String: NSColor] = [
        "idle": NSColor(red: 0.53, green: 0.53, blue: 0.6, alpha: 1),
        "thinking": NSColor(red: 1.0, green: 0.87, blue: 0, alpha: 1),
        "running": NSColor(red: 0, green: 1.0, blue: 0.67, alpha: 1),
        "awaiting": NSColor(red: 0, green: 0.8, blue: 1.0, alpha: 1),
        "resting": NSColor(red: 0.4, green: 0.4, blue: 0.53, alpha: 1),
    ]
}

// MARK: - Data Model

struct WidgetData: Codable {
    let status: String?
    let frame: String?
    let color: String?
    let context_percent: Double?
    let timestamp: Double?
    let border_width: Int?
    let border_pulse: Bool?
}

// MARK: - Pulsing Border View

class PulsingBorderView: NSView {
    var borderColor: NSColor = Config.statusColors["idle"]!
    var pulsePhase: Double = 0

    override func draw(_ dirtyRect: NSRect) {
        let path = NSBezierPath(roundedRect: bounds.insetBy(dx: 2, dy: 2),
                                 xRadius: Config.cornerRadius,
                                 yRadius: Config.cornerRadius)

        // Background
        NSColor(red: 0.05, green: 0.05, blue: 0.08, alpha: Config.bgAlpha).setFill()
        path.fill()

        // Pulsing border
        let intensity = CGFloat((sin(pulsePhase) + 1) / 2)
        let alpha = 0.4 + 0.6 * intensity
        borderColor.withAlphaComponent(alpha).setStroke()
        path.lineWidth = Config.borderWidth + intensity * 1.5
        path.stroke()
    }

    func pulse() {
        pulsePhase += Config.pulseSpeed
        needsDisplay = true
    }
}

// MARK: - Widget Window Controller

class WidgetWindowController: NSWindowController {
    var borderView: PulsingBorderView!
    var textField: NSTextField!
    var pulseTimer: Timer?
    var pollTimer: Timer?
    var currentStatus = "idle"

    convenience init() {
        // Create frameless window
        let window = NSWindow(
            contentRect: NSRect(origin: .zero, size: Config.windowSize),
            styleMask: [.borderless],
            backing: .buffered,
            defer: false
        )

        self.init(window: window)

        setupWindow()
        setupViews()
        startTimers()
        positionWindow()
    }

    func setupWindow() {
        guard let window = window else { return }

        window.isOpaque = false
        window.backgroundColor = .clear
        window.hasShadow = true

        // CRITICAL: These settings allow appearing above fullscreen apps
        window.level = NSWindow.Level(rawValue: Int(CGWindowLevelForKey(.maximumWindow)))
        window.collectionBehavior = [
            .canJoinAllSpaces,
            .stationary,
            .fullScreenAuxiliary,
            .ignoresCycle
        ]

        // Allow mouse events to pass through for dragging
        window.isMovableByWindowBackground = true
        window.acceptsMouseMovedEvents = true
    }

    func setupViews() {
        guard let window = window else { return }

        // Border view (background)
        borderView = PulsingBorderView(frame: NSRect(origin: .zero, size: Config.windowSize))
        borderView.wantsLayer = true
        window.contentView = borderView

        // Text field for ASCII display
        textField = NSTextField(frame: borderView.bounds.insetBy(dx: 20, dy: 20))
        textField.isEditable = false
        textField.isBordered = false
        textField.isSelectable = false
        textField.backgroundColor = .clear
        textField.textColor = Config.statusColors["idle"]
        textField.font = NSFont.monospacedSystemFont(ofSize: Config.fontSize, weight: .medium)
        textField.alignment = .left
        textField.stringValue = "Loading..."
        borderView.addSubview(textField)
    }

    func positionWindow() {
        guard let window = window, let screen = NSScreen.main else { return }
        let screenRect = screen.visibleFrame
        let x = screenRect.maxX - Config.windowSize.width - 40
        let y = screenRect.maxY - Config.windowSize.height - 40
        window.setFrameOrigin(NSPoint(x: x, y: y))
    }

    func startTimers() {
        // Pulse animation timer
        pulseTimer = Timer.scheduledTimer(withTimeInterval: 0.04, repeats: true) { [weak self] _ in
            self?.borderView.pulse()
        }

        // JSON polling timer
        pollTimer = Timer.scheduledTimer(withTimeInterval: Config.pollInterval, repeats: true) { [weak self] _ in
            self?.loadData()
        }

        // Initial load
        loadData()
    }

    func loadData() {
        // Use FileManager to bypass URL caching
        let path = Config.jsonPath
        guard FileManager.default.fileExists(atPath: path),
              let data = FileManager.default.contents(atPath: path),
              let widgetData = try? JSONDecoder().decode(WidgetData.self, from: data) else {
            return
        }

        // Update display
        if let frame = widgetData.frame {
            textField.stringValue = frame
        }

        // Update status color
        if let status = widgetData.status, status != currentStatus {
            currentStatus = status
            let color = Config.statusColors[status] ?? Config.statusColors["idle"]!
            borderView.borderColor = color
            textField.textColor = color
        }
    }

    func show() {
        window?.makeKeyAndOrderFront(nil)
    }
}

// MARK: - App Delegate

class AppDelegate: NSObject, NSApplicationDelegate {
    var widgetController: WidgetWindowController!

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Hide dock icon
        NSApp.setActivationPolicy(.accessory)

        widgetController = WidgetWindowController()
        widgetController.show()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return true
    }
}

// MARK: - Single Instance Check (lock file)

let lockFilePath = "/tmp/clarvis-widget.lock"

func acquireLock() -> Bool {
    let fm = FileManager.default
    let pid = ProcessInfo.processInfo.processIdentifier

    // Check if lock file exists with a running process
    if fm.fileExists(atPath: lockFilePath),
       let content = try? String(contentsOfFile: lockFilePath, encoding: .utf8),
       let existingPID = Int32(content.trimmingCharacters(in: .whitespacesAndNewlines)) {
        // Check if process is still running
        if kill(existingPID, 0) == 0 {
            return false  // Another instance is running
        }
    }

    // Write our PID to lock file
    try? "\(pid)".write(toFile: lockFilePath, atomically: true, encoding: .utf8)
    return true
}

func releaseLock() {
    try? FileManager.default.removeItem(atPath: lockFilePath)
}

// MARK: - Main

// Ensure single instance
if !acquireLock() {
    print("ClarvisWidget is already running. Exiting.")
    exit(0)
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
