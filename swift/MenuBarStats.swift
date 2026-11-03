//
// MenuBarStats.swift
// Menu bar item for Odysseus: what the local models and the Mac are doing, and a
// way to unload them. Reads Docker Model Runner (127.0.0.1:12434) and the kernel
// directly, so it needs no login and works while the window is closed.
//
// The icon is animated (MenuBarView.swift): a ring shows memory in use and a moon orbits
// faster while the GPU is busy. A click opens a small card; "Details" opens the rest.
//

import Cocoa
import Darwin
import IOKit
import SwiftUI

struct ModelRow {
    let name: String
    let sizeGB: Double?
    let contextTokens: Int?
    let embedding: Bool

    /// "huggingface.co/unsloth/qwen3.6-35b-a3b-gguf:UD-Q3_K_S" -> "qwen3.6-35b-a3b"
    var shortName: String {
        let last = name.split(separator: "/").last.map(String.init) ?? name
        let base = last.split(separator: ":").first.map(String.init) ?? last
        return base.hasSuffix("-gguf") ? String(base.dropLast(5)) : base
    }
}

struct MemoryStats {
    let totalGB: Double
    let usedGB: Double
    let compressedGB: Double
    let cachedGB: Double
    let swapUsedGB: Double
    let pressure: Int  // 1 normal, 2 warning, 4 critical

    var availableGB: Double { max(totalGB - usedGB, 0) }
    var fraction: Double { totalGB > 0 ? min(usedGB / totalGB, 1) : 0 }
    var pressureName: String { pressure >= 4 ? "critical" : (pressure >= 2 ? "warning" : "normal") }
}

struct MenuStats {
    var port = 7860
    var serverUp = false
    var runnerUp = false
    var models: [ModelRow] = []
    var memory: MemoryStats?
    var load1 = 0.0
    var cpuPercent: Double?
    var gpuPercent: Double?
    var thermal = "Nominal"
    var uptime: TimeInterval = 0
    var guardNote: String?

    var chatModels: [ModelRow] { models.filter { !$0.embedding } }
    var loadedGB: Double { chatModels.compactMap { $0.sizeGB }.reduce(0, +) }
}

struct RunnerStats {
    var serverUp = false
    var runnerUp = false
    var models: [ModelRow] = []
}

struct SystemStats {
    var memory: MemoryStats?
    var load1 = 0.0
    var cpuPercent: Double?
    var gpuPercent: Double?
    var thermal = "Nominal"
    var uptime: TimeInterval = 0
    var guardNote: String?
}

extension MenuStats {
    mutating func merge(_ r: RunnerStats) {
        serverUp = r.serverUp
        runnerUp = r.runnerUp
        models = r.models
    }

    mutating func merge(_ s: SystemStats) {
        memory = s.memory
        load1 = s.load1
        cpuPercent = s.cpuPercent
        gpuPercent = s.gpuPercent
        thermal = s.thermal
        uptime = s.uptime
        guardNote = s.guardNote
    }

    /// What the icon should be doing. Memory trouble outranks everything.
    var iconMode: MenuBarIcon.Mode {
        if !serverUp && !runnerUp { return .off }
        if let m = memory, m.pressure >= 4 { return .critical }
        if let m = memory, m.pressure >= 2 { return .warning }
        if (gpuPercent ?? 0) >= 20 { return .busy }
        return chatModels.isEmpty ? .idle : .loaded
    }
}

enum MenuRow {
    case header(String)
    case info(String)
    case action(String, Selector)
    case separator
}

func resolveRepoDir() -> String {
    if let env = ProcessInfo.processInfo.environment["ODYSSEUS_REPO_DIR"] { return env }
    return "/Users/shamit/Documents/Docker/Odysseus"
}

/// CPU use between two calls, from the kernel's per-core tick counters.
final class SystemSampler {
    private var previous: (busy: UInt64, total: UInt64)?

    func cpuPercent() -> Double? {
        var cores: natural_t = 0
        var info: processor_info_array_t?
        var count: mach_msg_type_number_t = 0
        guard host_processor_info(mach_host_self(), PROCESSOR_CPU_LOAD_INFO, &cores, &info, &count) == KERN_SUCCESS,
              let info = info else { return nil }
        defer { vm_deallocate(mach_task_self_, vm_address_t(bitPattern: info), vm_size_t(count) * vm_size_t(MemoryLayout<integer_t>.stride)) }

        var busy: UInt64 = 0, total: UInt64 = 0
        for core in 0..<Int(cores) {
            let base = core * Int(CPU_STATE_MAX)
            let user = UInt64(info[base + Int(CPU_STATE_USER)]), sys = UInt64(info[base + Int(CPU_STATE_SYSTEM)])
            let idle = UInt64(info[base + Int(CPU_STATE_IDLE)]), nice = UInt64(info[base + Int(CPU_STATE_NICE)])
            busy += user + sys + nice
            total += user + sys + nice + idle
        }
        defer { previous = (busy, total) }
        guard let prev = previous, total > prev.total else { return nil }
        return Double(busy - prev.busy) / Double(total - prev.total) * 100
    }
}

enum StatsProvider {
    static let runnerRoot = ProcessInfo.processInfo.environment["ODYSSEUS_DMR_URL"] ?? "http://127.0.0.1:12434"

    // MARK: Reading

    /// Everything once. `sampler` should be primed (called once before) for a CPU figure.
    static func collect(port: Int, repoDir: String, sampler: SystemSampler? = nil) -> MenuStats {
        var stats = MenuStats()
        stats.port = port
        stats.merge(readRunner(port: port))
        stats.merge(readSystem(repoDir: repoDir, sampler: sampler))
        return stats
    }

    /// Network side: is the server up, which models are resident. Can take a few seconds.
    static func readRunner(port: Int) -> RunnerStats {
        var out = RunnerStats()
        out.serverUp = httpStatus("http://127.0.0.1:\(port)/", timeout: 1.0).map { (200...499).contains($0) } ?? false
        if let resident = httpJSON("\(runnerRoot)/engines/ps") as? [[String: Any]] {
            out.runnerUp = true
            let known = (httpJSON("\(runnerRoot)/models") as? [[String: Any]]) ?? []
            out.models = resident.compactMap { entry in
                guard let name = entry["model_name"] as? String else { return nil }
                let config = known.first { ($0["tags"] as? [String])?.contains(name) == true }?["config"] as? [String: Any]
                return ModelRow(
                    name: name,
                    sizeGB: (config?["size"] as? String).flatMap(parseSizeGB),
                    contextTokens: config?["context_size"] as? Int,
                    embedding: (entry["mode"] as? String) == "embedding"
                )
            }
        } else {
            out.runnerUp = httpStatus("\(runnerRoot)/models", timeout: 1.0) != nil
        }
        return out
    }

    /// Kernel side: cheap, no network, safe to call every couple of seconds.
    static func readSystem(repoDir: String, sampler: SystemSampler?) -> SystemStats {
        var out = SystemStats()
        out.memory = readMemory()
        out.load1 = loadAverage()
        out.cpuPercent = sampler?.cpuPercent()
        out.gpuPercent = gpuUtilization()
        out.thermal = thermalName()
        out.uptime = uptimeSeconds()
        out.guardNote = readGuardNote(repoDir: repoDir)
        return out
    }

    static func readMemory() -> MemoryStats? {
        var total: UInt64 = 0
        var size = MemoryLayout<UInt64>.size
        guard sysctlbyname("hw.memsize", &total, &size, nil, 0) == 0 else { return nil }

        var vm = vm_statistics64()
        var count = mach_msg_type_number_t(MemoryLayout<vm_statistics64_data_t>.stride / MemoryLayout<integer_t>.stride)
        let status = withUnsafeMutablePointer(to: &vm) {
            $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                host_statistics64(mach_host_self(), HOST_VM_INFO64, $0, &count)
            }
        }
        guard status == KERN_SUCCESS else { return nil }
        let page = Double(getpagesize())
        // Activity Monitor's "Memory Used": app + wired + compressed (file cache is reclaimable).
        let used = (Double(vm.internal_page_count) + Double(vm.wire_count) + Double(vm.compressor_page_count)) * page
        let cached = (Double(vm.external_page_count) + Double(vm.purgeable_count)) * page
        let compressed = Double(vm.compressor_page_count) * page

        var swap = xsw_usage()
        var swapSize = MemoryLayout<xsw_usage>.size
        _ = sysctlbyname("vm.swapusage", &swap, &swapSize, nil, 0)

        var level: Int32 = 1
        var levelSize = MemoryLayout<Int32>.size
        _ = sysctlbyname("kern.memorystatus_vm_pressure_level", &level, &levelSize, nil, 0)

        let gib = Double(1 << 30)
        return MemoryStats(totalGB: Double(total) / gib, usedGB: used / gib, compressedGB: compressed / gib,
                           cachedGB: cached / gib, swapUsedGB: Double(swap.xsu_used) / gib, pressure: Int(level))
    }

    static func loadAverage() -> Double {
        var loads = [Double](repeating: 0, count: 3)
        return getloadavg(&loads, 3) > 0 ? loads[0] : 0
    }

    /// GPU busy percent from the accelerator's own counters (no privileges needed).
    static func gpuUtilization() -> Double? {
        var iterator: io_iterator_t = 0
        guard IOServiceGetMatchingServices(kIOMainPortDefault, IOServiceMatching("IOAccelerator"), &iterator) == KERN_SUCCESS else { return nil }
        defer { IOObjectRelease(iterator) }
        var best: Double?
        var entry = IOIteratorNext(iterator)
        while entry != 0 {
            let stats = IORegistryEntryCreateCFProperty(entry, "PerformanceStatistics" as CFString, kCFAllocatorDefault, 0)?
                .takeRetainedValue() as? [String: Any]
            if let value = (stats?["Device Utilization %"] as? NSNumber)?.doubleValue { best = max(best ?? 0, value) }
            IOObjectRelease(entry)
            entry = IOIteratorNext(iterator)
        }
        return best
    }

    static func thermalName() -> String {
        switch ProcessInfo.processInfo.thermalState {
        case .nominal: return "Nominal"
        case .fair: return "Fair"
        case .serious: return "Serious"
        case .critical: return "Critical"
        @unknown default: return "Unknown"
        }
    }

    static func uptimeSeconds() -> TimeInterval {
        var boot = timeval()
        var size = MemoryLayout<timeval>.size
        guard sysctlbyname("kern.boottime", &boot, &size, nil, 0) == 0 else { return 0 }
        return max(Date().timeIntervalSince1970 - Double(boot.tv_sec), 0)
    }

    /// "Odysseus unloaded models at 15:02 (memory pressure critical)" for 24 h after it happens.
    static func readGuardNote(repoDir: String) -> String? {
        let path = "\(repoDir)/logs/memory-guard.json"
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: path),
              let modified = attrs[.modificationDate] as? Date, Date().timeIntervalSince(modified) < 86_400,
              let data = FileManager.default.contents(atPath: path),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let at = json["at"] as? String, let reason = json["reason"] as? String else { return nil }
        return "Unloaded models at \(at.suffix(8).prefix(5)) (\(reason))"
    }

    // "14.29GiB", "934.69MiB", "4.28GB" -> GiB
    static func parseSizeGB(_ text: String) -> Double? {
        let units: [String: Double] = ["kib": 1.0 / 1_048_576, "mib": 1.0 / 1024, "gib": 1, "kb": 1e3 / 1_073_741_824,
                                       "mb": 1e6 / 1_073_741_824, "gb": 1e9 / 1_073_741_824]
        let lower = text.lowercased().trimmingCharacters(in: .whitespaces)
        for (suffix, factor) in units where lower.hasSuffix(suffix) {
            if let value = Double(lower.dropLast(suffix.count)) { return value * factor }
        }
        return nil
    }

    // MARK: Actions

    /// Unload every chat model. Returns how many were asked to unload.
    @discardableResult
    static func unloadAll() -> Int {
        guard let resident = httpJSON("\(runnerRoot)/engines/ps") as? [[String: Any]] else { return 0 }
        let names = resident.compactMap { ($0["model_name"] as? String) }
            .filter { name in !resident.contains { ($0["model_name"] as? String) == name && ($0["mode"] as? String) == "embedding" } }
        guard !names.isEmpty, let body = try? JSONSerialization.data(withJSONObject: ["models": names]) else { return 0 }
        _ = httpJSON("\(runnerRoot)/engines/unload", method: "POST", body: body, timeout: 30)
        return names.count
    }

    // MARK: HTTP

    static func httpJSON(_ url: String, method: String = "GET", body: Data? = nil, timeout: TimeInterval = 2.0) -> Any? {
        guard let target = URL(string: url) else { return nil }
        var request = URLRequest(url: target, timeoutInterval: timeout)
        request.httpMethod = method
        if let body = body {
            request.httpBody = body
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let done = DispatchSemaphore(value: 0)
        let box = Box()
        URLSession.shared.dataTask(with: request) { data, response, _ in
            if let data = data, let http = response as? HTTPURLResponse, http.statusCode < 300 {
                box.value = try? JSONSerialization.jsonObject(with: data)
            }
            done.signal()
        }.resume()
        _ = done.wait(timeout: .now() + timeout + 1)
        return box.value
    }

    static func httpStatus(_ url: String, timeout: TimeInterval) -> Int? {
        guard let target = URL(string: url) else { return nil }
        let done = DispatchSemaphore(value: 0)
        let box = Box()
        URLSession.shared.dataTask(with: URLRequest(url: target, timeoutInterval: timeout)) { _, response, _ in
            box.value = (response as? HTTPURLResponse)?.statusCode
            done.signal()
        }.resume()
        _ = done.wait(timeout: .now() + timeout + 1)
        return box.value as? Int
    }

    private final class Box: @unchecked Sendable { var value: Any? }

    // MARK: Text

    static func fmt(_ gb: Double) -> String { String(format: gb >= 10 ? "%.0f GB" : "%.1f GB", gb) }

    static func contextText(_ tokens: Int?) -> String? {
        guard let t = tokens, t > 0 else { return nil }
        return t >= 1024 ? "\(t / 1024)k ctx" : "\(t) ctx"
    }

    static func uptimeText(_ seconds: TimeInterval) -> String {
        let minutes = Int(seconds / 60), hours = minutes / 60, days = hours / 24
        if days > 0 { return "\(days)d \(hours % 24)h" }
        if hours > 0 { return "\(hours)h \(minutes % 60)m" }
        return "\(minutes)m"
    }

    /// Short model line for the card: size and context, or why there is no model.
    static func modelDetail(_ model: ModelRow) -> String {
        let parts = [model.sizeGB.map(fmt), contextText(model.contextTokens), model.embedding ? "embedding" : nil]
        return parts.compactMap { $0 }.joined(separator: " · ")
    }

    /// Plain-text version of the card, for `--dump-menubar` and checks without a screen.
    static func summaryLines(for stats: MenuStats) -> [String] {
        var lines: [String] = []
        lines.append(stats.serverUp ? "Odysseus: running on :\(stats.port)" : "Odysseus: server not running")
        if !stats.runnerUp {
            lines.append("Model runner: not reachable")
        } else if stats.chatModels.isEmpty {
            lines.append("Model: none loaded")
        } else {
            for m in stats.chatModels { lines.append("Model: \(m.shortName) · \(modelDetail(m))") }
        }
        if let mem = stats.memory {
            let pct = Int((mem.fraction * 100).rounded())
            lines.append("Memory: \(fmt(mem.usedGB)) of \(fmt(mem.totalGB)) (\(pct)%) · pressure \(mem.pressureName)")
            lines.append("  compressed \(fmt(mem.compressedGB)) · cached \(fmt(mem.cachedGB)) · swap \(fmt(mem.swapUsedGB))")
        }
        lines.append("GPU: \(stats.gpuPercent.map { String(format: "%.0f%%", $0) } ?? "n/a") · CPU: \(stats.cpuPercent.map { String(format: "%.0f%%", $0) } ?? "n/a") · load \(String(format: "%.1f", stats.load1))")
        lines.append("Thermal: \(stats.thermal.lowercased()) · up \(uptimeText(stats.uptime))")
        if let note = stats.guardNote { lines.append(note) }
        lines.append("Icon: \(stats.iconMode)")
        return lines
    }

    /// The right-click menu: quick actions only (the details live in the card).
    static func rows(for stats: MenuStats, unload: Selector, open: Selector, log: Selector, quit: Selector) -> [MenuRow] {
        var rows: [MenuRow] = []
        rows.append(.header(stats.serverUp ? "Odysseus  ● running on :\(stats.port)" : "Odysseus  ○ server not running"))
        rows.append(.separator)
        rows.append(.action(stats.chatModels.isEmpty ? "Unload all models" : "Unload all models (\(stats.chatModels.count))", unload))
        rows.append(.action("Open Odysseus", open))
        rows.append(.action("Show server log", log))
        rows.append(.separator)
        rows.append(.action("Quit Odysseus", quit))
        return rows
    }

    static func tooltip(for stats: MenuStats) -> String {
        var parts = ["Odysseus"]
        if !stats.chatModels.isEmpty { parts.append("\(fmt(stats.loadedGB)) of models loaded") }
        if let mem = stats.memory { parts.append("memory \(Int((mem.fraction * 100).rounded()))% (\(mem.pressureName))") }
        return parts.joined(separator: " · ")
    }
}

// MARK: - Model shared with the card

struct MenuBarActions {
    let open: () -> Void
    let unload: () -> Void
    let log: () -> Void
    let quit: () -> Void
}

/// What the card shows. Histories are one sample every `MenuBarStats.sampleInterval` seconds.
final class MenuBarModel: ObservableObject {
    static let historyLength = 90

    @Published var stats = MenuStats()
    @Published var cpuHistory: [Double] = []
    @Published var gpuHistory: [Double] = []
    @Published var memoryHistory: [Double] = []
    @Published var expanded = false

    func record(_ stats: MenuStats) {
        self.stats = stats
        func push(_ list: inout [Double], _ value: Double?) {
            guard let value = value else { return }
            list.append(value)
            if list.count > Self.historyLength { list.removeFirst(list.count - Self.historyLength) }
        }
        push(&cpuHistory, stats.cpuPercent)
        push(&gpuHistory, stats.gpuPercent)
        push(&memoryHistory, stats.memory.map { $0.fraction * 100 })
    }
}

// MARK: - Controller

final class MenuBarStats: NSObject {
    static let sampleInterval: TimeInterval = 2.0

    private var statusItem: NSStatusItem!
    private let popover = NSPopover()
    private let model = MenuBarModel()
    private let systemQueue = DispatchQueue(label: "odysseus.menubar.system", qos: .utility)
    private let runnerQueue = DispatchQueue(label: "odysseus.menubar.runner", qos: .utility)
    private let sampler = SystemSampler()
    private var sampleTimer: Timer?
    private var animationTimer: Timer?
    private var animatedMode: MenuBarIcon.Mode?
    private var angle = 0.0
    private var lastFrame = Date()
    private var outsideClickMonitor: Any?
    private var ticks = 0
    private let port: Int
    private let repoDir: String
    private let onOpen: () -> Void
    private let onQuit: () -> Void

    init(port: Int, repoDir: String, onOpen: @escaping () -> Void, onQuit: @escaping () -> Void) {
        self.port = port
        self.repoDir = repoDir
        self.onOpen = onOpen
        self.onQuit = onQuit
        // The default slot is the one next to the notch, which a crowded bar (or an overlay app) covers.
        // Start 400 pt from the right edge instead (from the second launch on: macOS reads the position
        // at process start); once the user ⌘-drags it, macOS remembers their spot and this is not touched.
        let positionKey = "NSStatusItem Preferred Position odysseus-statusitem"
        if UserDefaults.standard.object(forKey: positionKey) == nil { UserDefaults.standard.set(400.0, forKey: positionKey) }
        super.init()
        model.stats.port = port
        installStatusItem()

        let actions = MenuBarActions(
            open: { [weak self] in self?.closePopover(); self?.onOpen() },
            unload: { [weak self] in self?.unloadAll() },
            log: { [weak self] in self?.showLog() },
            quit: { [weak self] in self?.quitApp() }
        )
        let controller = NSHostingController(rootView: MenuBarView(model: model, actions: actions) { [weak self] height in
            self?.popover.contentSize = NSSize(width: MenuBarView.width, height: height)
        })
        popover.contentViewController = controller
        popover.behavior = .transient
        popover.animates = true
        popover.contentSize = NSSize(width: MenuBarView.width, height: 260)

        sample()
        sampleTimer = Timer(timeInterval: Self.sampleInterval, repeats: true) { [weak self] _ in self?.sample() }
        RunLoop.main.add(sampleTimer!, forMode: .common)
    }

    private func installStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        statusItem.autosaveName = "odysseus-statusitem"  // keeps its place in the menu bar between launches
        statusItem.isVisible = true
        if let button = statusItem.button {
            button.image = MenuBarIcon.image(angle: angle, pulse: 0, memory: model.stats.memory?.fraction ?? 0, mode: mode)
            button.imagePosition = .imageOnly
            button.toolTip = StatsProvider.tooltip(for: model.stats)
            button.target = self
            button.action = #selector(clicked(_:))
            button.sendAction(on: [.leftMouseUp, .rightMouseUp])
        }
    }

    // MARK: Sampling

    private func sample() {
        ticks += 1
        let doRunner = (ticks - 1) % 3 == 0  // network side every ~6 s, kernel side every 2 s
        systemQueue.async { [weak self] in
            guard let self = self else { return }
            let system = StatsProvider.readSystem(repoDir: self.repoDir, sampler: self.sampler)
            DispatchQueue.main.async {
                var stats = self.model.stats
                stats.merge(system)
                self.apply(stats)
            }
        }
        if doRunner {
            runnerQueue.async { [weak self] in
                guard let self = self else { return }
                let runner = StatsProvider.readRunner(port: self.port)
                DispatchQueue.main.async {
                    var stats = self.model.stats
                    stats.merge(runner)
                    self.apply(stats)
                }
            }
        }
    }

    private func apply(_ stats: MenuStats) {
        model.record(stats)
        statusItem.button?.toolTip = StatsProvider.tooltip(for: stats)
        updateAnimation()
        renderIcon()
    }

    // MARK: Icon animation

    private var mode: MenuBarIcon.Mode { model.stats.iconMode }

    private var reduceMotion: Bool { NSWorkspace.shared.accessibilityDisplayShouldReduceMotion }

    /// Run the animation timer at the rate the current mode wants; stop it when the icon should be still.
    private func updateAnimation() {
        let wanted: MenuBarIcon.Mode? = (mode == .off || reduceMotion) ? nil : mode
        guard wanted != animatedMode else { return }
        animatedMode = wanted
        animationTimer?.invalidate()
        animationTimer = nil
        guard let wanted = wanted else { return }
        lastFrame = Date()
        let timer = Timer(timeInterval: 1.0 / wanted.framesPerSecond, repeats: true) { [weak self] _ in self?.advanceFrame() }
        RunLoop.main.add(timer, forMode: .common)
        animationTimer = timer
    }

    private func advanceFrame() {
        let now = Date()
        angle += now.timeIntervalSince(lastFrame) * mode.revolutionsPerSecond * 2 * .pi
        angle = angle.truncatingRemainder(dividingBy: 2 * .pi)
        lastFrame = now
        renderIcon()
    }

    private func renderIcon() {
        let pulse = (sin(Date().timeIntervalSinceReferenceDate * 5) + 1) / 2
        statusItem.button?.image = MenuBarIcon.image(angle: angle, pulse: pulse, memory: model.stats.memory?.fraction ?? 0, mode: mode)
    }

    // MARK: Clicks

    @objc private func clicked(_ sender: NSStatusBarButton) {
        let event = NSApp.currentEvent
        if event?.type == .rightMouseUp || event?.modifierFlags.contains(.control) == true {
            closePopover()
            showQuickMenu(from: sender)
        } else if popover.isShown {
            closePopover()
        } else {
            openPopover(from: sender)
        }
    }

    private func openPopover(from button: NSStatusBarButton) {
        model.expanded = false  // the first click is always the small card
        popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
        popover.contentViewController?.view.window?.makeKey()
        outsideClickMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] _ in
            self?.closePopover()
        }
        sample()
    }

    private func closePopover() {
        popover.performClose(nil)
        if let monitor = outsideClickMonitor {
            NSEvent.removeMonitor(monitor)
            outsideClickMonitor = nil
        }
    }

    private func showQuickMenu(from button: NSStatusBarButton) {
        let menu = NSMenu()
        for row in StatsProvider.rows(for: model.stats, unload: #selector(unloadAllFromMenu), open: #selector(openFromMenu),
                                      log: #selector(showLogFromMenu), quit: #selector(quitFromMenu)) {
            switch row {
            case .separator:
                menu.addItem(.separator())
            case .header(let text):
                let item = NSMenuItem(title: text, action: nil, keyEquivalent: "")
                item.attributedTitle = NSAttributedString(string: text, attributes: [.font: NSFont.boldSystemFont(ofSize: 13)])
                item.isEnabled = false
                menu.addItem(item)
            case .info(let text):
                let item = NSMenuItem(title: text, action: nil, keyEquivalent: "")
                item.isEnabled = false
                menu.addItem(item)
            case .action(let text, let selector):
                let item = NSMenuItem(title: text, action: selector, keyEquivalent: "")
                item.target = self
                menu.addItem(item)
            }
        }
        menu.popUp(positioning: nil, at: NSPoint(x: 0, y: button.bounds.height + 4), in: button)
    }

    /// For checks without a screen grab: after a few seconds, write whether the item is on screen and what it shows.
    func writeDebug(to path: String) {
        let openCard = ProcessInfo.processInfo.environment["ODYSSEUS_MENUBAR_DEBUG_OPEN"] != nil  // also open the card, expanded if "details"
        DispatchQueue.main.asyncAfter(deadline: .now() + 4) { [weak self] in
            guard let self = self, let button = self.statusItem.button else { return }
            if openCard {
                self.openPopover(from: button)
                self.model.expanded = ProcessInfo.processInfo.environment["ODYSSEUS_MENUBAR_DEBUG_OPEN"] == "details"
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + (openCard ? 1.5 : 0)) { self.writeDebugNow(to: path) }
        }
    }

    private func writeDebugNow(to path: String) {
        let button = statusItem.button
        let menuRows = StatsProvider.rows(for: model.stats, unload: #selector(unloadAllFromMenu), open: #selector(openFromMenu),
                                          log: #selector(showLogFromMenu), quit: #selector(quitFromMenu))
        let popoverWindow = popover.contentViewController?.view.window
        let info: [String: Any] = [
            "visible": button?.window?.isVisible ?? false,
            "frame": button?.window.map { NSStringFromRect($0.frame) } ?? "none",
            "screenTop": NSScreen.main.map { NSStringFromRect($0.frame) } ?? "none",
            "hasImage": button?.image != nil,
            "animating": animationTimer != nil,
            "mode": "\(mode)",
            "popoverShown": popover.isShown,
            "popoverFrame": popoverWindow.map { NSStringFromRect($0.frame) } ?? "none",
            "summary": StatsProvider.summaryLines(for: model.stats),
            "menu": menuRows.map { row -> String in
                switch row {
                case .separator: return "---"
                case .header(let t), .info(let t), .action(let t, _): return t
                }
            },
        ]
        if let data = try? JSONSerialization.data(withJSONObject: info, options: [.prettyPrinted]) {
            try? data.write(to: URL(fileURLWithPath: path))
        }
    }

    // MARK: Actions

    private func unloadAll() {
        runnerQueue.async { [weak self] in
            StatsProvider.unloadAll()
            DispatchQueue.main.async { self?.sample() }
        }
    }

    private func showLog() { NSWorkspace.shared.open(URL(fileURLWithPath: "\(repoDir)/logs/odysseus-app.log")) }

    private func quitApp() { onQuit() }

    @objc private func unloadAllFromMenu() { unloadAll() }
    @objc private func openFromMenu() { onOpen() }
    @objc private func showLogFromMenu() { showLog() }
    @objc private func quitFromMenu() { quitApp() }
}
