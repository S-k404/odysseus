//
// MenuBarStats.swift
// Menu bar item for Odysseus: what the local models and the Mac are doing, and a
// way to unload them. Reads Docker Model Runner (127.0.0.1:12434) and the kernel
// directly, so it needs no login and works while the window is closed.
//

import Cocoa
import Darwin

struct ModelRow {
    let name: String
    let sizeGB: Double?
    let contextTokens: Int?
    let embedding: Bool
}

struct MemoryStats {
    let totalGB: Double
    let usedGB: Double
    let swapUsedGB: Double
    let pressure: Int  // 1 normal, 2 warning, 4 critical

    var availableGB: Double { max(totalGB - usedGB, 0) }
    var pressureName: String { pressure >= 4 ? "critical" : (pressure >= 2 ? "warning" : "normal") }
}

struct MenuStats {
    var port = 7860
    var serverUp = false
    var runnerUp = false
    var models: [ModelRow] = []
    var memory: MemoryStats?
    var load1 = 0.0
    var guardNote: String?
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

enum StatsProvider {
    static let runnerRoot = ProcessInfo.processInfo.environment["ODYSSEUS_DMR_URL"] ?? "http://127.0.0.1:12434"

    // MARK: Reading

    static func collect(port: Int, repoDir: String) -> MenuStats {
        var stats = MenuStats()
        stats.port = port
        stats.serverUp = httpStatus("http://127.0.0.1:\(port)/", timeout: 1.0).map { (200...499).contains($0) } ?? false
        stats.memory = readMemory()
        stats.load1 = loadAverage()
        stats.guardNote = readGuardNote(repoDir: repoDir)

        if let resident = httpJSON("\(runnerRoot)/engines/ps") as? [[String: Any]] {
            stats.runnerUp = true
            let known = (httpJSON("\(runnerRoot)/models") as? [[String: Any]]) ?? []
            stats.models = resident.compactMap { entry in
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
            stats.runnerUp = httpStatus("\(runnerRoot)/models", timeout: 1.0) != nil
        }
        return stats
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
        // Activity Monitor's "Memory Used": app + wired + compressed (file cache is reclaimable).
        let pages = UInt64(vm.internal_page_count) + UInt64(vm.wire_count) + UInt64(vm.compressor_page_count)
        let used = Double(pages) * Double(getpagesize())

        var swap = xsw_usage()
        var swapSize = MemoryLayout<xsw_usage>.size
        _ = sysctlbyname("vm.swapusage", &swap, &swapSize, nil, 0)

        var level: Int32 = 1
        var levelSize = MemoryLayout<Int32>.size
        _ = sysctlbyname("kern.memorystatus_vm_pressure_level", &level, &levelSize, nil, 0)

        let gib = Double(1 << 30)
        return MemoryStats(totalGB: Double(total) / gib, usedGB: used / gib,
                           swapUsedGB: Double(swap.xsu_used) / gib, pressure: Int(level))
    }

    static func loadAverage() -> Double {
        var loads = [Double](repeating: 0, count: 3)
        return getloadavg(&loads, 3) > 0 ? loads[0] : 0
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

    // MARK: Menu content

    static func fmt(_ gb: Double) -> String { String(format: gb >= 10 ? "%.0f GB" : "%.1f GB", gb) }

    static func contextText(_ tokens: Int?) -> String? {
        guard let t = tokens, t > 0 else { return nil }
        return t >= 1024 ? "\(t / 1024)k ctx" : "\(t) ctx"
    }

    /// Pure: the menu as rows, so it can be printed in tests as well as shown.
    static func rows(for stats: MenuStats, unload: Selector, open: Selector, log: Selector, quit: Selector) -> [MenuRow] {
        var rows: [MenuRow] = []
        rows.append(.header(stats.serverUp ? "Odysseus  ● running on :\(stats.port)" : "Odysseus  ○ server not running"))
        rows.append(.separator)

        rows.append(.header(stats.runnerUp ? "Models in memory" : "Model runner not reachable"))
        let chat = stats.models.filter { !$0.embedding }
        if stats.runnerUp && chat.isEmpty { rows.append(.info("None loaded")) }
        for model in stats.models {
            let short = model.name.split(separator: "/").last.map(String.init) ?? model.name
            let detail = [model.sizeGB.map(fmt), contextText(model.contextTokens), model.embedding ? "embedding" : nil]
                .compactMap { $0 }.joined(separator: " · ")
            rows.append(.info(detail.isEmpty ? short : "\(short) — \(detail)"))
        }
        rows.append(.separator)

        if let mem = stats.memory {
            let pct = mem.totalGB > 0 ? Int((mem.usedGB / mem.totalGB * 100).rounded()) : 0
            rows.append(.info("Memory: \(fmt(mem.usedGB)) of \(fmt(mem.totalGB)) in use (\(pct)%)"))
            rows.append(.info("Available: \(fmt(mem.availableGB)) · Swap: \(fmt(mem.swapUsedGB))"))
            rows.append(.info("Pressure: \(mem.pressureName)" + (mem.pressure >= 2 ? "  ⚠︎" : "")))
        }
        rows.append(.info(String(format: "CPU load: %.1f (1 min)", stats.load1)))
        if let note = stats.guardNote { rows.append(.info(note)) }
        rows.append(.separator)

        rows.append(.action(chat.isEmpty ? "Unload all models" : "Unload all models (\(chat.count))", unload))
        rows.append(.action("Open Odysseus", open))
        rows.append(.action("Show server log", log))
        rows.append(.separator)
        rows.append(.action("Quit Odysseus", quit))
        return rows
    }

    /// Title next to the icon: loaded weights, or a warning when memory is tight.
    static func title(for stats: MenuStats) -> String {
        var parts: [String] = []
        if let mem = stats.memory, mem.pressure >= 2 { parts.append("⚠︎") }
        let loaded = stats.models.filter { !$0.embedding }.compactMap { $0.sizeGB }.reduce(0, +)
        if !stats.models.filter({ !$0.embedding }).isEmpty { parts.append(String(format: "%.0fG", loaded)) }
        return parts.isEmpty ? "" : " " + parts.joined(separator: " ")
    }
}

final class MenuBarStats: NSObject, NSMenuDelegate {
    private let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private let menu = NSMenu()
    private let queue = DispatchQueue(label: "odysseus.menubar", qos: .utility)
    private var timer: Timer?
    private var latest = MenuStats()
    private let port: Int
    private let repoDir: String
    private let onOpen: () -> Void
    private let onQuit: () -> Void

    init(port: Int, repoDir: String, onOpen: @escaping () -> Void, onQuit: @escaping () -> Void) {
        self.port = port
        self.repoDir = repoDir
        self.onOpen = onOpen
        self.onQuit = onQuit
        super.init()
        latest.port = port
        if let button = statusItem.button {
            let image = NSImage(systemSymbolName: "cpu", accessibilityDescription: "Odysseus model stats")
            image?.isTemplate = true
            button.image = image
            button.imagePosition = .imageLeading
            button.toolTip = "Odysseus: local models and memory"
        }
        menu.delegate = self
        statusItem.menu = menu
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 5.0, repeats: true) { [weak self] _ in self?.refresh() }
    }

    func refresh() {
        queue.async { [weak self] in
            guard let self = self else { return }
            let stats = StatsProvider.collect(port: self.port, repoDir: self.repoDir)
            DispatchQueue.main.async {
                self.latest = stats
                self.statusItem.button?.title = StatsProvider.title(for: stats)
            }
        }
    }

    func menuNeedsUpdate(_ menu: NSMenu) {
        menu.removeAllItems()
        let rows = StatsProvider.rows(for: latest, unload: #selector(unloadAll), open: #selector(openApp),
                                      log: #selector(showLog), quit: #selector(quitApp))
        for row in rows {
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
        refresh()  // so the next time it opens it is fresh
    }

    /// For checks without a screen grab: after a few seconds, write whether the item is on screen and its menu.
    func writeDebug(to path: String) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 4) { [weak self] in
            guard let self = self else { return }
            self.menuNeedsUpdate(self.menu)
            let button = self.statusItem.button
            let info: [String: Any] = [
                "visible": button?.window?.isVisible ?? false,
                "frame": button?.window.map { NSStringFromRect($0.frame) } ?? "none",
                "screenTop": NSScreen.main.map { NSStringFromRect($0.frame) } ?? "none",
                "title": button?.title ?? "",
                "hasImage": button?.image != nil,
                "menu": self.menu.items.map { $0.isSeparatorItem ? "---" : $0.title },
            ]
            if let data = try? JSONSerialization.data(withJSONObject: info, options: [.prettyPrinted]) {
                try? data.write(to: URL(fileURLWithPath: path))
            }
        }
    }

    @objc private func unloadAll() {
        queue.async { [weak self] in
            StatsProvider.unloadAll()
            self?.refresh()
        }
    }

    @objc private func openApp() { onOpen() }

    @objc private func showLog() {
        NSWorkspace.shared.open(URL(fileURLWithPath: "\(repoDir)/logs/odysseus-app.log"))
    }

    @objc private func quitApp() { onQuit() }
}
