import Cocoa
import WebKit

// MARK: - Status Model

struct ClaudeStatus: Equatable {
    var status: String = "idle"
    var tool: String = ""
    var color: String = "gray"
    var text: String = "Starting..."
    var contextPercent: Double = 0

    var isActive: Bool {
        ["running", "thinking", "awaiting", "resting"].contains(status)
    }

    // Map legacy status names to new simplified states
    var mappedStatus: String {
        switch status {
        case "working", "executing", "writing", "reading", "reviewing":
            return "running"
        case "thinking":
            return "thinking"
        case "awaiting":
            return "awaiting"
        case "resting", "idle", "offline":
            return "resting"
        default:
            return "resting"
        }
    }
}

// MARK: - WebView Display

// Custom WebView that allows mouse events to pass through for window dragging
class DraggableWebView: WKWebView {
    override func mouseDown(with event: NSEvent) {
        // Let the window handle dragging
        window?.performDrag(with: event)
    }
}

class PixelArtDisplayView: NSView, WKNavigationDelegate {
    private var webView: DraggableWebView!
    private var isWebViewReady = false
    private var pendingStatus: ClaudeStatus?

    var status = ClaudeStatus() {
        didSet {
            if isWebViewReady {
                updateWebView()
            } else {
                pendingStatus = status
            }
        }
    }

    override init(frame: NSRect) {
        super.init(frame: frame)
        setupWebView()
    }

    required init?(coder: NSCoder) {
        super.init(coder: coder)
        setupWebView()
    }

    private func setupWebView() {
        // Configure WebView for transparent background
        let config = WKWebViewConfiguration()
        config.preferences.setValue(true, forKey: "developerExtrasEnabled")

        webView = DraggableWebView(frame: bounds, configuration: config)
        webView.autoresizingMask = [.width, .height]
        webView.navigationDelegate = self

        // Transparent background
        webView.setValue(false, forKey: "drawsBackground")

        addSubview(webView)

        // Load the renderer HTML
        loadRenderer()
    }

    private func loadRenderer() {
        // Get path to renderer/index.html relative to the app
        let basePath = "/Users/shepardxia/Desktop/directory/central-hub/renderer"
        let htmlPath = "\(basePath)/index.html"

        if let htmlURL = URL(string: "file://\(htmlPath)") {
            let baseURL = URL(string: "file://\(basePath)/")!
            webView.loadFileURL(htmlURL, allowingReadAccessTo: baseURL)
        }
    }

    // MARK: - WKNavigationDelegate

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        isWebViewReady = true

        // Apply any pending status
        if let pending = pendingStatus {
            status = pending
            pendingStatus = nil
        } else {
            updateWebView()
        }
    }

    // MARK: - Status Updates

    private func updateWebView() {
        let state = status.mappedStatus
        let tool = status.tool.replacingOccurrences(of: "'", with: "\\'")

        let js = "setState('\(state)', '\(tool)')"
        webView.evaluateJavaScript(js) { _, error in
            if let error = error {
                print("JS Error: \(error)")
            }
        }
    }

    override func draw(_ dirtyRect: NSRect) {
        // Draw rounded background behind WebView
        let bg = NSBezierPath(roundedRect: bounds, xRadius: 12, yRadius: 12)
        NSColor(white: 0, alpha: 0.7).setFill()
        bg.fill()
    }
}
