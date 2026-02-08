import Cocoa
import Foundation
import Speech
import AVFoundation

// MARK: - Configuration

// RGB as [r, g, b] array
typealias RGBArray = [CGFloat]

extension RGBArray {
    func toNSColor() -> NSColor? {
        guard self.count == 3 else { return nil }
        return NSColor(red: self[0], green: self[1], blue: self[2], alpha: 1)
    }
}

struct ThemeConfig: Codable {
    var base: String = "modern"
    var overrides: [String: RGBArray]? = nil
}

struct DisplayConfig: Codable {
    var grid_width: Int = 29
    var grid_height: Int = 12
    var corner_radius: CGFloat = 24
    var bg_alpha: CGFloat = 0.75
    var font_size: CGFloat = 14
    var font_name: String = "Courier"
    var border_width: CGFloat = 2
    var pulse_speed: Double = 0.1
}

struct WidgetConfigFile: Codable {
    var theme: ThemeConfig = ThemeConfig()
    var display: DisplayConfig = DisplayConfig()
}

struct WidgetConfig {
    var gridWidth: Int = 29
    var gridHeight: Int = 12
    var cornerRadius: CGFloat = 24
    var bgAlpha: CGFloat = 0.75
    var fontSize: CGFloat = 14
    var fontName: String = "Courier"
    var borderWidth: CGFloat = 2
    var pulseSpeed: Double = 0.1

    // Derived from grid + font at load time
    var charWidth: CGFloat = 8.4
    var lineHeight: CGFloat = 16.8
    var windowWidth: CGFloat = 280
    var windowHeight: CGFloat = 220

    static let padding: CGFloat = 20  // textField inset from window edges

    static func load() -> WidgetConfig {
        let binaryPath = CommandLine.arguments[0]
        let projectRoot = (binaryPath as NSString).deletingLastPathComponent + "/.."
        let configPath = (projectRoot as NSString).appendingPathComponent("config.json")

        guard let data = FileManager.default.contents(atPath: configPath),
              let file = try? JSONDecoder().decode(WidgetConfigFile.self, from: data) else {
            return WidgetConfig()
        }

        var config = WidgetConfig(
            gridWidth: file.display.grid_width,
            gridHeight: file.display.grid_height,
            cornerRadius: file.display.corner_radius,
            bgAlpha: file.display.bg_alpha,
            fontSize: file.display.font_size,
            fontName: file.display.font_name,
            borderWidth: file.display.border_width,
            pulseSpeed: file.display.pulse_speed
        )

        // Measure actual font metrics — single source of truth for rendering + hit-testing
        let font = NSFont(name: config.fontName, size: config.fontSize)
            ?? NSFont.monospacedSystemFont(ofSize: config.fontSize, weight: .medium)
        config.charWidth = ("M" as NSString).size(withAttributes: [.font: font]).width
        config.lineHeight = config.fontSize * 1.2

        // Derive window size from grid × font metrics
        config.windowWidth = CGFloat(config.gridWidth) * config.charWidth + 2 * padding
        config.windowHeight = CGFloat(config.gridHeight) * config.lineHeight + 2 * padding

        return config
    }
}

struct Config {
    static let socketPath = "/tmp/clarvis-widget.sock"

    static let widgetConfig = WidgetConfig.load()
    static var windowSize: NSSize { NSSize(width: widgetConfig.windowWidth, height: widgetConfig.windowHeight) }

    static var font: NSFont {
        NSFont(name: widgetConfig.fontName, size: widgetConfig.fontSize)
            ?? NSFont.monospacedSystemFont(ofSize: widgetConfig.fontSize, weight: .medium)
    }
}

// MARK: - Grid Renderer

class GridRenderer {
    /// 256-entry ANSI color cache, built once at startup.
    static let colorCache: [NSColor] = {
        var colors = [NSColor]()
        colors.reserveCapacity(256)

        // 0-15: Standard + bright colors
        let std: [(CGFloat, CGFloat, CGFloat)] = [
            (0, 0, 0),       // 0: black
            (0.8, 0, 0),     // 1: red
            (0, 0.8, 0),     // 2: green
            (0.8, 0.8, 0),   // 3: yellow
            (0, 0, 0.8),     // 4: blue
            (0.8, 0, 0.8),   // 5: magenta
            (0, 0.8, 0.8),   // 6: cyan
            (0.75, 0.75, 0.75), // 7: white
            (0.5, 0.5, 0.5), // 8: bright black (gray)
            (1, 0, 0),       // 9: bright red
            (0, 1, 0),       // 10: bright green
            (1, 1, 0),       // 11: bright yellow
            (0, 0, 1),       // 12: bright blue
            (1, 0, 1),       // 13: bright magenta
            (0, 1, 1),       // 14: bright cyan
            (1, 1, 1),       // 15: bright white
        ]
        for (r, g, b) in std { colors.append(NSColor(red: r, green: g, blue: b, alpha: 1)) }

        // 16-231: 6×6×6 color cube
        for i in 0..<216 {
            let r = CGFloat((i / 36) % 6) / 5.0
            let g = CGFloat((i / 6) % 6) / 5.0
            let b = CGFloat(i % 6) / 5.0
            colors.append(NSColor(red: r, green: g, blue: b, alpha: 1))
        }

        // 232-255: Grayscale ramp
        for i in 0..<24 {
            let gray = CGFloat(i) / 23.0
            colors.append(NSColor(white: gray, alpha: 1))
        }

        return colors
    }()

    /// Build an NSAttributedString from grid rows and per-cell color arrays.
    /// Color 0 → use `defaultColor` (theme color).
    static func build(rows: [String], colors: [[Int]], defaultColor: NSColor, font: NSFont) -> NSAttributedString {
        let result = NSMutableAttributedString()

        let paragraphStyle = NSMutableParagraphStyle()
        paragraphStyle.lineSpacing = 0
        paragraphStyle.paragraphSpacing = 0
        paragraphStyle.minimumLineHeight = font.pointSize * 1.2
        paragraphStyle.maximumLineHeight = font.pointSize * 1.2
        paragraphStyle.lineBreakMode = .byClipping

        for (rowIdx, row) in rows.enumerated() {
            if rowIdx > 0 {
                result.append(NSAttributedString(string: "\n", attributes: [.font: font, .paragraphStyle: paragraphStyle]))
            }

            let rowColors = rowIdx < colors.count ? colors[rowIdx] : []
            let chars = Array(row)
            var runStart = 0

            while runStart < chars.count {
                let code = runStart < rowColors.count ? rowColors[runStart] : 0
                let color = code > 0 && code < 256 ? colorCache[code] : defaultColor

                // Accumulate run of same color code (integer compare, not object identity)
                var runEnd = runStart + 1
                while runEnd < chars.count {
                    let nextCode = runEnd < rowColors.count ? rowColors[runEnd] : 0
                    if nextCode != code { break }
                    runEnd += 1
                }

                let runStr = String(chars[runStart..<runEnd])
                let attrs: [NSAttributedString.Key: Any] = [
                    .foregroundColor: color,
                    .font: font,
                    .paragraphStyle: paragraphStyle
                ]
                result.append(NSAttributedString(string: runStr, attributes: attrs))
                runStart = runEnd
            }
        }

        return result
    }
}

// MARK: - Data Model

struct WidgetData: Codable {
    let rows: [String]?
    let cell_colors: [[Int]]?
    let theme_color: [Double]?  // RGB [r, g, b] for border + default text

    var nsColor: NSColor {
        guard let rgb = theme_color, rgb.count == 3 else {
            return NSColor.gray
        }
        return NSColor(red: CGFloat(rgb[0]), green: CGFloat(rgb[1]), blue: CGFloat(rgb[2]), alpha: 1.0)
    }
}

// MARK: - Click Regions

struct ClickRegion {
    let id: String
    let row: Int
    let col: Int
    let width: Int
    let height: Int

    init?(from dict: [String: Any]) {
        guard let id = dict["id"] as? String,
              let row = dict["row"] as? Int,
              let col = dict["col"] as? Int,
              let width = dict["width"] as? Int,
              let height = dict["height"] as? Int else { return nil }
        self.id = id
        self.row = row
        self.col = col
        self.width = width
        self.height = height
    }

    func contains(row r: Int, col c: Int) -> Bool {
        r >= row && r < row + height && c >= col && c < col + width
    }
}

// MARK: - ASR Manager

class ASRManager {
    private let speechRecognizer: SFSpeechRecognizer?
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private let audioEngine = AVAudioEngine()
    private var timeoutTimer: Timer?
    private var silenceTimer: Timer?
    private var lastTranscript = ""
    private var hasDeliveredResult = false

    /// Called once with (success, text?, error?)
    var onResult: ((Bool, String?, String?) -> Void)?

    init(locale: Locale = Locale(identifier: "en-US")) {
        self.speechRecognizer = SFSpeechRecognizer(locale: locale)
            ?? SFSpeechRecognizer()
    }

    var isAvailable: Bool { speechRecognizer?.isAvailable ?? false }

    func requestAuthorization(completion: @escaping (Bool) -> Void) {
        SFSpeechRecognizer.requestAuthorization { status in
            DispatchQueue.main.async { completion(status == .authorized) }
        }
    }

    func startRecognition(timeout: TimeInterval = 10.0, silenceTimeout: TimeInterval = 3.0) {
        stopRecognition()
        hasDeliveredResult = false
        lastTranscript = ""

        guard let recognizer = speechRecognizer, recognizer.isAvailable else {
            deliverResult(success: false, error: "Speech recognizer not available")
            return
        }

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        if #available(macOS 13.0, *) {
            request.requiresOnDeviceRecognition = true
        }

        let inputNode = audioEngine.inputNode
        let recordingFormat = inputNode.outputFormat(forBus: 0)

        inputNode.installTap(onBus: 0, bufferSize: 1024, format: recordingFormat) { buffer, _ in
            request.append(buffer)
        }

        audioEngine.prepare()
        do {
            try audioEngine.start()
        } catch {
            deliverResult(success: false, error: "Audio engine failed: \(error.localizedDescription)")
            return
        }

        self.recognitionRequest = request
        let silenceDuration = silenceTimeout

        recognitionTask = recognizer.recognitionTask(with: request) { [weak self] result, error in
            DispatchQueue.main.async {
                guard let self = self, !self.hasDeliveredResult else { return }

                if let result = result {
                    self.lastTranscript = result.bestTranscription.formattedString

                    // Reset silence timer on new speech
                    self.silenceTimer?.invalidate()
                    self.silenceTimer = Timer.scheduledTimer(
                        withTimeInterval: silenceDuration, repeats: false
                    ) { _ in self.finalize() }

                    if result.isFinal {
                        self.finalize()
                    }
                }

                if let error = error {
                    if self.lastTranscript.isEmpty {
                        self.deliverResult(success: false, error: error.localizedDescription)
                    } else {
                        self.finalize()
                    }
                }
            }
        }

        // Overall timeout
        timeoutTimer = Timer.scheduledTimer(withTimeInterval: timeout, repeats: false) { [weak self] _ in
            guard let self = self, !self.hasDeliveredResult else { return }
            if self.lastTranscript.isEmpty {
                self.deliverResult(success: false, error: "Timeout — no speech detected")
            } else {
                self.finalize()
            }
        }
    }

    private func finalize() {
        deliverResult(success: true, text: lastTranscript)
    }

    private func deliverResult(success: Bool, text: String? = nil, error: String? = nil) {
        guard !hasDeliveredResult else { return }
        hasDeliveredResult = true
        stopRecognition()
        onResult?(success, text, error)
    }

    func stopRecognition() {
        timeoutTimer?.invalidate()
        timeoutTimer = nil
        silenceTimer?.invalidate()
        silenceTimer = nil

        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)

        recognitionRequest?.endAudio()
        recognitionRequest = nil

        recognitionTask?.cancel()
        recognitionTask = nil
    }
}

// MARK: - Socket Client

class SocketClient {
    private let socketPath: String
    private var fileDescriptor: Int32 = -1
    private var isConnected = false
    private var readThread: Thread?
    private var shouldRun = true

    var onFrame: ((WidgetData) -> Void)?
    var onCommand: ((String, [String: Any]) -> Void)?
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

    func send(_ message: [String: Any]) {
        guard isConnected, fileDescriptor >= 0 else { return }
        guard let data = try? JSONSerialization.data(withJSONObject: message),
              var json = String(data: data, encoding: .utf8) else { return }
        json += "\n"
        json.withCString { ptr in
            _ = Darwin.write(fileDescriptor, ptr, strlen(ptr))
        }
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

                // Check if this is a command (has "method" key) or a frame
                if let json = try? JSONSerialization.jsonObject(with: lineData) as? [String: Any],
                   let method = json["method"] as? String {
                    let params = json["params"] as? [String: Any] ?? [:]
                    DispatchQueue.main.async {
                        self.onCommand?(method, params)
                    }
                } else if let frame = try? JSONDecoder().decode(WidgetData.self, from: lineData) {
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
    var borderColor: NSColor = NSColor.gray
    var pulsePhase: Double = 0

    override func draw(_ dirtyRect: NSRect) {
        let path = NSBezierPath(roundedRect: bounds.insetBy(dx: 2, dy: 2),
                                 xRadius: Config.widgetConfig.cornerRadius,
                                 yRadius: Config.widgetConfig.cornerRadius)

        NSColor(red: 0.05, green: 0.05, blue: 0.08, alpha: Config.widgetConfig.bgAlpha).setFill()
        path.fill()

        let intensity = CGFloat((sin(pulsePhase) + 1) / 2)
        let alpha = 0.4 + 0.6 * intensity
        borderColor.withAlphaComponent(alpha).setStroke()
        path.lineWidth = Config.widgetConfig.borderWidth + intensity * 1.5
        path.stroke()
    }

    func pulse() {
        pulsePhase += Config.widgetConfig.pulseSpeed
        needsDisplay = true
    }

    // Tracking area ensures mouseMoved events fire even when window is not key
    // (required for hover cursor feedback on our borderless, non-key widget).
    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        for area in trackingAreas { removeTrackingArea(area) }
        addTrackingArea(NSTrackingArea(
            rect: bounds,
            options: [.mouseMoved, .mouseEnteredAndExited, .activeAlways],
            owner: self.window,
            userInfo: nil
        ))
    }
}

// MARK: - Clickable Window

class ClickableWindow: NSWindow {
    var clickRegions: [ClickRegion] = []
    var gridRows = 0
    var gridCols = 0

    override func sendEvent(_ event: NSEvent) {
        switch event.type {
        case .leftMouseDown:
            // With isMovableByWindowBackground, leftMouseUp is consumed by the
            // window-dragging machinery and never reaches sendEvent.  Handle
            // clicks on mouseDown: if the hit lands inside a click region, fire
            // immediately and skip super (preventing a drag); otherwise fall
            // through to super so the window remains draggable.
            if let (row, col) = gridCell(at: event.locationInWindow),
               let region = clickRegions.first(where: { $0.contains(row: row, col: col) }) {
                let socketClient = (NSApp.delegate as? AppDelegate)?.widgetController?.socketClient
                socketClient?.send([
                    "method": "region_click",
                    "params": ["id": region.id]
                ])
                return  // swallow event — no drag
            }
            super.sendEvent(event)
        case .mouseMoved:
            updateCursorForMousePosition(event.locationInWindow)
            super.sendEvent(event)
        default:
            super.sendEvent(event)
        }
    }

    private func updateCursorForMousePosition(_ windowPoint: NSPoint) {
        guard let (row, col) = gridCell(at: windowPoint) else {
            NSCursor.arrow.set()
            return
        }
        if clickRegions.contains(where: { $0.contains(row: row, col: col) }) {
            NSCursor.pointingHand.set()
        } else {
            NSCursor.arrow.set()
        }
    }

    private func gridCell(at windowPoint: NSPoint) -> (row: Int, col: Int)? {
        guard let textField = contentView?.subviews.first(where: { $0 is NSTextField }) as? NSTextField,
              let cell = textField.cell else {
            return nil
        }

        // Convert window point to textField's local coordinate system.
        // NSTextField.isFlipped = true (Apple default), so Y=0 is the TOP
        // of the text field and Y increases downward — matching grid row order.
        let localPoint = textField.convert(windowPoint, from: nil)

        // Get the actual text drawing area (accounts for cell internal padding).
        let titleRect = cell.titleRect(forBounds: textField.bounds)

        // Compute position relative to the text content area.
        let textX = localPoint.x - titleRect.origin.x
        let textY = localPoint.y - titleRect.origin.y

        // Map to grid coordinates using config-derived font metrics.
        // No Y inversion needed — flipped coords already run top-to-bottom,
        // matching grid row 0 at the top.
        let col = Int(textX / Config.widgetConfig.charWidth)
        let row = Int(textY / Config.widgetConfig.lineHeight)

        guard row >= 0, row < gridRows, col >= 0, col < gridCols else { return nil }
        return (row, col)
    }

    func setGridDimensions(rows: Int, cols: Int) {
        gridRows = rows
        gridCols = cols
    }

}

// MARK: - Widget Window Controller

class WidgetWindowController: NSWindowController {
    var borderView: PulsingBorderView!
    var textField: NSTextField!
    var responseOverlay: NSScrollView!
    var responseTextView: NSTextView!
    var pulseTimer: Timer?
    var socketClient: SocketClient!
    var asrManager: ASRManager!
    var socketConnected = false

    convenience init() {
        let window = ClickableWindow(
            contentRect: NSRect(origin: .zero, size: Config.windowSize),
            styleMask: [.borderless],
            backing: .buffered,
            defer: false
        )

        self.init(window: window)

        setupWindow()
        setupViews()
        setupResponseOverlay()
        setupASR()
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
        textField.textColor = .gray
        textField.font = Config.font
        textField.alignment = .left
        textField.stringValue = "Connecting..."

        // CRITICAL: Prevent line wrapping which causes display corruption
        textField.cell?.wraps = false
        textField.cell?.isScrollable = false
        textField.lineBreakMode = .byClipping
        textField.maximumNumberOfLines = 0  // No limit, but won't wrap
        textField.usesSingleLineMode = false  // Allow newlines in content

        borderView.addSubview(textField)
    }

    func setupResponseOverlay() {
        let inset: CGFloat = 16
        let overlayFrame = borderView.bounds.insetBy(dx: inset, dy: inset)

        let scrollView = NSScrollView(frame: overlayFrame)
        scrollView.hasVerticalScroller = true
        scrollView.hasHorizontalScroller = false
        scrollView.autohidesScrollers = true
        scrollView.drawsBackground = false
        scrollView.isHidden = true

        let textView = NSTextView(frame: scrollView.contentView.bounds)
        textView.isEditable = false
        textView.isSelectable = false
        textView.drawsBackground = false
        textView.textColor = .white
        textView.font = NSFont.systemFont(ofSize: 13, weight: .regular)
        textView.textContainerInset = NSSize(width: 4, height: 4)
        textView.isVerticallyResizable = true
        textView.isHorizontallyResizable = false
        textView.textContainer?.widthTracksTextView = true
        textView.autoresizingMask = [.width]

        scrollView.documentView = textView

        borderView.addSubview(scrollView)
        responseOverlay = scrollView
        responseTextView = textView
    }

    func setupASR() {
        asrManager = ASRManager()
        asrManager.requestAuthorization { granted in
            if !granted {
                NSLog("ClarvisWidget: Speech recognition not authorized")
            }
        }
    }

    func setupSocket() {
        socketClient = SocketClient()

        socketClient.onFrame = { [weak self] data in
            self?.updateDisplay(data)
        }

        socketClient.onCommand = { [weak self] method, params in
            self?.handleCommand(method, params)
        }

        socketClient.onConnectionChange = { [weak self] connected in
            self?.socketConnected = connected
            if !connected {
                self?.asrManager.stopRecognition()  // Release mic on disconnect
                self?.clearResponse()
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

    }

    func updateDisplay(_ data: WidgetData) {
        let color = data.nsColor
        borderView.borderColor = color

        if let rows = data.rows, let cellColors = data.cell_colors {
            let font = Config.font
            textField.attributedStringValue = GridRenderer.build(
                rows: rows, colors: cellColors, defaultColor: color, font: font)

            // Update grid dimensions for click hit-testing (bounds check only;
            // charWidth/lineHeight are derived once at startup in Config).
            if let clickableWindow = window as? ClickableWindow {
                clickableWindow.setGridDimensions(rows: rows.count, cols: rows.first?.count ?? 0)
            }
        }
    }

    func positionWindow() {
        guard let window = window, let screen = NSScreen.main else { return }
        let screenRect = screen.visibleFrame
        let x = screenRect.maxX - Config.windowSize.width - 40
        let y = screenRect.maxY - Config.windowSize.height - 40
        window.setFrameOrigin(NSPoint(x: x, y: y))
    }

    // MARK: - Command Handling

    // Voice pipeline IPC protocol — typed in Python as frozen dataclasses
    // (see clarvis/services/voice_orchestrator.py for canonical definitions):
    //
    //   Inbound  (daemon -> widget):
    //     start_asr     { timeout: Float, silence_timeout: Float, id: String }
    //     show_response { text: String }
    //     clear_response {}
    //
    //   Outbound (widget -> daemon):
    //     asr_result    { success: Bool, id: String, text?: String, error?: String }
    func handleCommand(_ method: String, _ params: [String: Any]) {
        switch method {
        case "start_asr":
            let timeout = params["timeout"] as? TimeInterval ?? 10.0
            let silenceTimeout = params["silence_timeout"] as? TimeInterval ?? 3.0
            let id = params["id"] as? String ?? ""
            startASR(timeout: timeout, silenceTimeout: silenceTimeout, id: id)
        case "show_response":
            if let text = params["text"] as? String {
                showResponse(text)
            }
        case "clear_response":
            clearResponse()
        case "set_click_regions":
            if let regionsArray = params["regions"] as? [[String: Any]] {
                updateClickRegions(regionsArray)
            }
        default:
            break
        }
    }

    func updateClickRegions(_ regionsData: [[String: Any]]) {
        guard let clickableWindow = window as? ClickableWindow else { return }
        clickableWindow.clickRegions = regionsData.compactMap { ClickRegion(from: $0) }
    }

    func startASR(timeout: TimeInterval, silenceTimeout: TimeInterval, id: String) {
        asrManager.onResult = { [weak self] success, text, error in
            guard let self = self else { return }
            var result: [String: Any] = ["success": success, "id": id]
            if let text = text { result["text"] = text }
            if let error = error { result["error"] = error }

            self.socketClient.send([
                "method": "asr_result",
                "params": result
            ])
        }
        asrManager.startRecognition(timeout: timeout, silenceTimeout: silenceTimeout)
    }

    func showResponse(_ text: String) {
        responseTextView.string = text
        responseOverlay.isHidden = false
        textField.isHidden = true

        // Scroll to bottom for streaming updates
        responseTextView.scrollToEndOfDocument(nil)
    }

    func clearResponse() {
        responseOverlay.isHidden = true
        textField.isHidden = false
        responseTextView.string = ""
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
