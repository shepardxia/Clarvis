import Cocoa
import Foundation

// MARK: - Single Instance Check

func acquireLock() -> Bool {
    let lockFile = "/tmp/claude-status-overlay.lock"
    let lockFD = open(lockFile, O_CREAT | O_RDWR, 0o644)
    if lockFD == -1 || flock(lockFD, LOCK_EX | LOCK_NB) == -1 { return false }
    write(lockFD, String(getpid()), String(getpid()).count)
    return true
}

// MARK: - Status Watcher

class StatusWatcher {
    private let statusPath = "/tmp/claude-status.json"
    private var dirSource: DispatchSourceFileSystemObject?
    private var lastMod: Date?
    var onChange: ((ClaudeStatus) -> Void)?

    func start() {
        let dirFD = open("/tmp", O_EVTONLY)
        guard dirFD != -1 else { return }

        dirSource = DispatchSource.makeFileSystemObjectSource(
            fileDescriptor: dirFD,
            eventMask: .write,
            queue: .main
        )

        dirSource?.setEventHandler { [weak self] in self?.checkFile() }
        dirSource?.setCancelHandler { close(dirFD) }
        dirSource?.resume()

        checkFile()
    }

    private func checkFile() {
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: statusPath),
              let mod = attrs[.modificationDate] as? Date else { return }

        if lastMod == nil || mod > lastMod! {
            lastMod = mod
            onChange?(readStatus())
        }
    }

    func readStatus() -> ClaudeStatus {
        guard let data = FileManager.default.contents(atPath: statusPath),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return ClaudeStatus(status: "offline", color: "gray", text: "No status")
        }
        return ClaudeStatus(
            status: json["status"] as? String ?? "idle",
            tool: json["tool"] as? String ?? "",
            color: json["color"] as? String ?? "gray",
            text: json["text"] as? String ?? "",
            contextPercent: json["context_percent"] as? Double ?? 0
        )
    }
}

// MARK: - Weather Watcher

class WeatherWatcher {
    private let weatherPath = "/tmp/central-hub-weather.json"
    private var dirSource: DispatchSourceFileSystemObject?
    private var lastMod: Date?
    var onChange: ((WeatherType) -> Void)?

    func start() {
        let dirFD = open("/tmp", O_EVTONLY)
        guard dirFD != -1 else { return }

        dirSource = DispatchSource.makeFileSystemObjectSource(
            fileDescriptor: dirFD,
            eventMask: .write,
            queue: .main
        )

        dirSource?.setEventHandler { [weak self] in self?.checkFile() }
        dirSource?.setCancelHandler { close(dirFD) }
        dirSource?.resume()

        checkFile()
    }

    private func checkFile() {
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: weatherPath),
              let mod = attrs[.modificationDate] as? Date else { return }

        if lastMod == nil || mod > lastMod! {
            lastMod = mod
            onChange?(readWeather())
        }
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

// MARK: - Config Watcher

class ConfigWatcher {
    private let configPath = "/tmp/claude-overlay-config.json"
    private var dirSource: DispatchSourceFileSystemObject?
    private var lastMod: Date?
    var onChange: ((OverlayConfig) -> Void)?

    func start() {
        let dirFD = open("/tmp", O_EVTONLY)
        guard dirFD != -1 else { return }

        dirSource = DispatchSource.makeFileSystemObjectSource(
            fileDescriptor: dirFD,
            eventMask: .write,
            queue: .main
        )

        dirSource?.setEventHandler { [weak self] in self?.checkFile() }
        dirSource?.setCancelHandler { close(dirFD) }
        dirSource?.resume()

        checkFile()
    }

    private func checkFile() {
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: configPath),
              let mod = attrs[.modificationDate] as? Date else { return }

        if lastMod == nil || mod > lastMod! {
            lastMod = mod
            onChange?(readConfig())
        }
    }

    func readConfig() -> OverlayConfig {
        return OverlayConfig.load()
    }
}

// MARK: - App Delegate

class AppDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var displayView: StatusDisplayView!
    let watcher = StatusWatcher()
    let weatherWatcher = WeatherWatcher()
    let configWatcher = ConfigWatcher()
    var idleStart: Date?
    var lastActivity: Date = Date()
    var inactivityTimer: Timer?
    let restingTimeout: TimeInterval = 5 * 60
    let idleTimeout: TimeInterval = 10 * 60

    func applicationDidFinishLaunching(_ notification: Notification) {
        let size = NSSize(width: 220, height: 200)
        let screen = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1920, height: 1080)
        let origin = NSPoint(x: screen.maxX - size.width - 20, y: screen.maxY - size.height - 20)

        window = NSWindow(
            contentRect: NSRect(origin: origin, size: size),
            styleMask: .borderless,
            backing: .buffered,
            defer: false
        )
        window.isOpaque = false
        window.backgroundColor = .clear
        window.level = .floating
        window.collectionBehavior = [.canJoinAllSpaces, .stationary]
        window.isMovableByWindowBackground = true

        displayView = StatusDisplayView(frame: NSRect(origin: .zero, size: size))
        window.contentView = displayView
        window.makeKeyAndOrderFront(nil)

        watcher.onChange = { [weak self] status in
            guard let self = self else { return }
            self.lastActivity = Date()
            self.displayView.status = status
            self.handleState(status)
        }
        watcher.start()

        weatherWatcher.onChange = { [weak self] weatherType in
            self?.displayView.weatherType = weatherType
        }
        weatherWatcher.start()

        configWatcher.onChange = { [weak self] newConfig in
            self?.handleConfigChange(newConfig)
        }
        configWatcher.start()

        inactivityTimer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in
            self?.checkInactivity()
        }
    }

    func checkInactivity() {
        let current = displayView.status.status
        let elapsed = Date().timeIntervalSince(lastActivity)

        if current == "awaiting" && elapsed >= restingTimeout {
            displayView.status = ClaudeStatus(status: "resting", color: "gray", text: "Resting")
            handleState(displayView.status)
        } else if current == "resting" && elapsed >= idleTimeout {
            displayView.status = ClaudeStatus(status: "idle", color: "gray", text: "Idle")
            handleState(displayView.status)
        }
    }

    func handleConfigChange(_ newConfig: OverlayConfig) {
        let oldConfig = displayView.config

        // Check if dimensions changed (requires full rebuild)
        let dimensionsChanged = newConfig.gridWidth != oldConfig.gridWidth ||
                                newConfig.gridHeight != oldConfig.gridHeight ||
                                newConfig.fontSize != oldConfig.fontSize

        if dimensionsChanged {
            print("📐 Config dimensions changed - requires app restart")
            // Could post notification to restart app or handle window resize here
        } else {
            print("🔄 Config reloaded - updating positions")
            displayView.updateConfig(newConfig)
        }
    }

    func handleState(_ status: ClaudeStatus) {
        let isIdle = status.status == "idle" || status.status == "offline"

        if isIdle {
            if idleStart == nil { idleStart = Date() }
            if let s = idleStart, Date().timeIntervalSince(s) >= 600 { window.orderOut(nil) }
        } else {
            idleStart = nil
            if !window.isVisible {
                let screen = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1920, height: 1080)
                window.setFrameOrigin(NSPoint(x: screen.maxX - 180, y: screen.maxY - 180))
                window.makeKeyAndOrderFront(nil)
            }
        }
    }
}

// MARK: - Main

@main
struct ClaudeStatusOverlayApp {
    static func main() {
        guard acquireLock() else { exit(0) }

        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.setActivationPolicy(.accessory)
        app.run()
    }
}
