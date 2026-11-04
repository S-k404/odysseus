//
// MemoryFreer.swift
// "Free more memory": the part of freeing memory that "Optimise memory" leaves alone. Optimise unloads Odysseus's own
// models; this lists the other apps using the most memory and quits the ones the owner ticks. Apps are asked to quit
// politely (one with unsaved work asks first). Terminals, Docker, IDEs and Odysseus itself are never offered.
// `--menubar-heavy-apps` prints the list without any UI.
//

import Cocoa
import Darwin

struct HeavyApp {
    let name: String
    let gb: Double
    let app: NSRunningApplication
}

enum MemoryFreer {
    /// Smaller apps are not worth a question.
    static let minimumGB = 0.4
    static let maxListed = 6
    /// Never offered (matched against the app's name and bundle id, lower-cased): they hold the owner's sessions or the
    /// local models' services, and a memory button should not close them.
    static let protected = ["finder", "odysseus", "docker", "terminal", "iterm", "ghostty", "warp", "kitty", "alacritty",
                            "xcode", "claude", "antigravity", "systemsettings", "activitymonitor"]

    /// Memory footprint of one process in GB (what Activity Monitor shows, compressed pages included); 0 if unreadable.
    static func footprintGB(pid: pid_t) -> Double {
        var info = rusage_info_current()
        let status = withUnsafeMutablePointer(to: &info) {
            $0.withMemoryRebound(to: rusage_info_t?.self, capacity: 1) { proc_pid_rusage(pid, RUSAGE_INFO_CURRENT, $0) }
        }
        return status == 0 ? Double(info.ri_phys_footprint) / Double(1 << 30) : 0
    }

    /// parent pid -> child pids, from one `ps` call.
    static func childMap() -> [pid_t: [pid_t]] {
        let ps = Process()
        ps.executableURL = URL(fileURLWithPath: "/bin/ps")
        ps.arguments = ["-axo", "pid=,ppid="]
        let pipe = Pipe()
        ps.standardOutput = pipe
        ps.standardError = FileHandle.nullDevice
        guard (try? ps.run()) != nil else { return [:] }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        ps.waitUntilExit()
        var map: [pid_t: [pid_t]] = [:]
        for line in (String(data: data, encoding: .utf8) ?? "").split(separator: "\n") {
            let fields = line.split(separator: " ")
            if fields.count == 2, let pid = pid_t(fields[0]), let parent = pid_t(fields[1]) { map[parent, default: []].append(pid) }
        }
        return map
    }

    /// An app's footprint plus its helper processes (a browser keeps its tabs in child processes).
    static func treeGB(root: pid_t, children: [pid_t: [pid_t]]) -> Double {
        var total = 0.0
        var stack = [root]
        var seen = Set<pid_t>()
        while let pid = stack.popLast() {
            guard seen.insert(pid).inserted else { continue }
            total += footprintGB(pid: pid)
            stack += children[pid] ?? []
        }
        return total
    }

    static func isProtected(name: String, bundleID: String) -> Bool {
        let key = "\(name) \(bundleID)".lowercased()
        return protected.contains { key.contains($0) }
    }

    /// The biggest ordinary apps that may be offered for quitting, largest first.
    static func heavyApps(limit: Int = maxListed) -> [HeavyApp] {
        let children = childMap()
        let me = ProcessInfo.processInfo.processIdentifier
        var found: [HeavyApp] = []
        for app in NSWorkspace.shared.runningApplications where app.activationPolicy == .regular && app.processIdentifier != me {
            let name = app.localizedName ?? app.bundleIdentifier ?? "App"
            if isProtected(name: name, bundleID: app.bundleIdentifier ?? "") { continue }
            let gb = treeGB(root: app.processIdentifier, children: children)
            if gb >= minimumGB { found.append(HeavyApp(name: name, gb: gb, app: app)) }
        }
        return Array(found.sorted { $0.gb > $1.gb }.prefix(limit))
    }

    /// Worth interrupting the owner for: macOS says memory is tight, or most of it is in use.
    static func isTight(_ memory: MemoryStats?) -> Bool {
        guard let m = memory else { return false }
        return m.pressure >= 2 || m.fraction >= 0.75
    }

    /// The question, one unticked box per app. Separate from `offer` so it can be rendered without being shown.
    static func makeAlert(_ apps: [HeavyApp], memory: MemoryStats?) -> (alert: NSAlert, rows: [(box: NSButton, app: HeavyApp)]) {
        let alert = NSAlert()
        alert.messageText = "Quit apps to free more memory?"
        var text = "Optimise memory unloads Odysseus's models. These other apps use the most memory now. "
            + "Tick the ones to quit; each is asked politely, so an app with unsaved work will ask first."
        if let m = memory, m.swapUsedGB >= 4 {
            text += " macOS is also holding \(StatsProvider.fmt(m.swapUsedGB)) of swap, which it gives back only slowly."
        }
        alert.informativeText = text

        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 6
        var rows: [(box: NSButton, app: HeavyApp)] = []
        for heavy in apps {
            let box = NSButton(checkboxWithTitle: "\(heavy.name)  ·  \(StatsProvider.fmt(heavy.gb))", target: nil, action: nil)
            box.state = .off  // nothing is quit unless the owner ticks it
            stack.addArrangedSubview(box)
            rows.append((box, heavy))
        }
        stack.setFrameSize(stack.fittingSize)
        alert.accessoryView = stack
        alert.addButton(withTitle: "Quit Selected")
        alert.addButton(withTitle: "Not Now")
        return (alert, rows)
    }

    /// Ask which apps to quit; the ones ticked get a polite quit request. Returns how many were asked. Main thread only.
    static func offer(_ apps: [HeavyApp], memory: MemoryStats?) -> Int {
        let (alert, rows) = makeAlert(apps, memory: memory)
        NSApp.activate(ignoringOtherApps: true)
        guard alert.runModal() == .alertFirstButtonReturn else { return 0 }
        let chosen = rows.filter { $0.box.state == .on }.map { $0.app }
        for heavy in chosen { _ = heavy.app.terminate() }
        return chosen.count
    }

    static func nothingToOffer() {
        let alert = NSAlert()
        alert.messageText = "No other app is using much memory"
        alert.informativeText = "Nothing outside Odysseus holds more than \(StatsProvider.fmt(minimumGB)) that is safe to offer."
        alert.addButton(withTitle: "OK")
        NSApp.activate(ignoringOtherApps: true)
        alert.runModal()
    }
}
