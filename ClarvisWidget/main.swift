import Cocoa
import Foundation

// MARK: - Configuration

struct Config {
    static let socketPath = "/tmp/clarvis-widget.sock"
    static let jsonPath = "/tmp/widget-display.json"  // Fallback
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
        "running": NSColor(red: 1.0, green: 0.6, blue: 0.2, alpha: 1),
        "awaiting": NSColor(red: 0, green: 0.85, blue: 0.5, alpha: 1),
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

// MARK: - Socket Client

class SocketClient {
    private let socketPath: String
    private var fileDescriptor: Int32 = -1
    private var isConnected = false
    private var readThread: Thread?
    private var shouldRun = true

    var onFrame: ((WidgetData) -> Void)?
    var onConnectionChange: ((Bool) -> Void)?

    init(socketPath: String = Config.socketPath) {
        self.socketPath = socketPath
    }

    func connect() {
        guard !isConnected else { return }

        fileDescriptor = socket(AF_UNIX, SOCK_STREAM, 0)
        guard fileDescriptor >= 0 else {
            scheduleReconnect()
            return
        }

        var addr = sockaddr_un()
        addr.sun_family = sa_family_t(AF_UNIX)
        withUnsafeMutablePointer(to: &addr.sun_path.0) { ptr in
            _ = socketPath.withCString { strcpy(ptr, $0) }
        }

        let result = withUnsafePointer(to: &addr) { ptr in
            ptr.withMemoryRebound(to: sockaddr.self, capacity: 1) { sockPtr in
                Darwin.connect(fileDescriptor, sockPtr, socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        }

        if result < 0 {
            close(fileDescriptor)
            fileDescriptor = -1
            scheduleReconnect()
            return
        }

        isConnected = true
        shouldRun = true

        DispatchQueue.main.async {
            self.onConnectionChange?(true)
        }

        readThread = Thread { [weak self] in
            self?.readLoop()
        }
        readThread?.start()
    }

    func disconnect() {
        shouldRun = false
        isConnected = false

        if fileDescriptor >= 0 {
            close(fileDescriptor)
            fileDescriptor = -1
        }

        DispatchQueue.main.async {
            self.onConnectionChange?(false)
        }
    }

    private func readLoop() {
        var buffer = Data()
        let readBuffer = UnsafeMutablePointer<UInt8>.allocate(capacity: 4096)
        defer { readBuffer.deallocate() }

        while shouldRun && fileDescriptor >= 0 {
            let bytesRead = read(fileDescriptor, readBuffer, 4096)

            if bytesRead <= 0 {
                handleDisconnect()
                return
            }

            buffer.append(readBuffer, count: bytesRead)

            while let newlineIndex = buffer.firstIndex(of: UInt8(ascii: "\n")) {
                let lineData = buffer[..<newlineIndex]
                buffer = Data(buffer[(newlineIndex + 1)...])

                if let frame = try? JSONDecoder().decode(WidgetData.self, from: lineData) {
                    DispatchQueue.main.async {
                        self.onFrame?(frame)
                    }
                }
            }
        }
    }

    private func handleDisconnect() {
        disconnect()
        scheduleReconnect()
    }

    private func scheduleReconnect() {
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) { [weak self] in
            guard let self = self, !self.isConnected else { return }
            self.connect()
        }
    }
}

// MARK: - Pulsing Border View

class PulsingBorderView: NSView {
    var borderColor: NSColor = Config.statusColors["idle"]!
    var pulsePhase: Double = 0

    override func draw(_ dirtyRect: NSRect) {
        let path = NSBezierPath(roundedRect: bounds.insetBy(dx: 2, dy: 2),
                                 xRadius: Config.cornerRadius,
                                 yRadius: Config.cornerRadius)

        NSColor(red: 0.05, green: 0.05, blue: 0.08, alpha: Config.bgAlpha).setFill()
        path.fill()

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
    var pollTimer: Timer?  // Fallback polling
    var socketClient: SocketClient!
    var currentStatus = "idle"
    var socketConnected = false

    convenience init() {
        let window = NSWindow(
            contentRect: NSRect(origin: .zero, size: Config.windowSize),
            styleMask: [.borderless],
            backing: .buffered,
            defer: false
        )

        self.init(window: window)

        setupWindow()
        setupViews()
        setupSocket()
        startTimers()
        positionWindow()
    }

    func setupWindow() {
        guard let window = window else { return }

        window.isOpaque = false
        window.backgroundColor = .clear
        window.hasShadow = true
        window.level = NSWindow.Level(rawValue: Int(CGWindowLevelForKey(.maximumWindow)))
        window.collectionBehavior = [
            .canJoinAllSpaces,
            .stationary,
            .fullScreenAuxiliary,
            .ignoresCycle
        ]
        window.isMovableByWindowBackground = true
        window.acceptsMouseMovedEvents = true
    }

    func setupViews() {
        guard let window = window else { return }

        borderView = PulsingBorderView(frame: NSRect(origin: .zero, size: Config.windowSize))
        borderView.wantsLayer = true
        window.contentView = borderView

        textField = NSTextField(frame: borderView.bounds.insetBy(dx: 20, dy: 20))
        textField.isEditable = false
        textField.isBordered = false
        textField.isSelectable = false
        textField.backgroundColor = .clear
        textField.textColor = Config.statusColors["idle"]
        textField.font = NSFont.monospacedSystemFont(ofSize: Config.fontSize, weight: .medium)
        textField.alignment = .left
        textField.stringValue = "Connecting..."
        borderView.addSubview(textField)
    }

    func setupSocket() {
        socketClient = SocketClient()

        socketClient.onFrame = { [weak self] data in
            self?.updateDisplay(data)
        }

        socketClient.onConnectionChange = { [weak self] connected in
            self?.socketConnected = connected
            if !connected {
                self?.textField.stringValue = "Reconnecting..."
            }
        }

        socketClient.connect()
    }

    func startTimers() {
        // Pulse animation
        pulseTimer = Timer.scheduledTimer(withTimeInterval: 0.04, repeats: true) { [weak self] _ in
            self?.borderView.pulse()
        }

        // Fallback file polling (only when socket not connected)
        pollTimer = Timer.scheduledTimer(withTimeInterval: Config.pollInterval, repeats: true) { [weak self] _ in
            guard let self = self, !self.socketConnected else { return }
            self.loadDataFromFile()
        }

        // Initial file load
        loadDataFromFile()
    }

    func loadDataFromFile() {
        let path = Config.jsonPath
        guard FileManager.default.fileExists(atPath: path),
              let data = FileManager.default.contents(atPath: path),
              let widgetData = try? JSONDecoder().decode(WidgetData.self, from: data) else {
            return
        }
        updateDisplay(widgetData)
    }

    func updateDisplay(_ data: WidgetData) {
        if let frame = data.frame {
            textField.stringValue = frame
        }

        if let status = data.status, status != currentStatus {
            currentStatus = status
            let color = Config.statusColors[status] ?? Config.statusColors["idle"]!
            borderView.borderColor = color
            textField.textColor = color
        }
    }

    func positionWindow() {
        guard let window = window, let screen = NSScreen.main else { return }
        let screenRect = screen.visibleFrame
        let x = screenRect.maxX - Config.windowSize.width - 40
        let y = screenRect.maxY - Config.windowSize.height - 40
        window.setFrameOrigin(NSPoint(x: x, y: y))
    }

    func show() {
        window?.makeKeyAndOrderFront(nil)
    }
}

// MARK: - App Delegate

class AppDelegate: NSObject, NSApplicationDelegate {
    var widgetController: WidgetWindowController!

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        widgetController = WidgetWindowController()
        widgetController.show()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return true
    }
}

// MARK: - Single Instance Check

let lockFilePath = "/tmp/clarvis-widget.lock"

func acquireLock() -> Bool {
    let fm = FileManager.default
    let pid = ProcessInfo.processInfo.processIdentifier

    if fm.fileExists(atPath: lockFilePath),
       let content = try? String(contentsOfFile: lockFilePath, encoding: .utf8),
       let existingPID = Int32(content.trimmingCharacters(in: .whitespacesAndNewlines)) {
        if kill(existingPID, 0) == 0 {
            return false
        }
    }

    try? "\(pid)".write(toFile: lockFilePath, atomically: true, encoding: .utf8)
    return true
}

func releaseLock() {
    try? FileManager.default.removeItem(atPath: lockFilePath)
}

// MARK: - Main

if !acquireLock() {
    print("ClarvisWidget is already running. Exiting.")
    exit(0)
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
