//
// main.swift
// Entry point for the Odysseus Mac app. `--dump-menubar` prints what the menu bar
// item would show (stats and menu rows) and exits, so it can be checked without a UI;
// `--render-menubar <dir>` writes PNGs of the card and icon;
// `--menubar-unload-all` unloads the chat models directly; `--menubar-optimise` does what "Optimise memory" does;
// `--menubar-heavy-apps` lists the other apps "Free more memory" would offer to quit.
//

import Cocoa

if CommandLine.arguments.contains("--dump-menubar") {
    let port = Int(ProcessInfo.processInfo.environment["ODYSSEUS_PORT"] ?? "") ?? 7860
    let sampler = SystemSampler()
    _ = sampler.cpuPercent()  // prime, so the second reading has a CPU figure
    Thread.sleep(forTimeInterval: 0.4)
    let stats = StatsProvider.collect(port: port, repoDir: resolveRepoDir(), sampler: sampler)
    print("tooltip: \(StatsProvider.tooltip(for: stats))")
    for line in StatsProvider.summaryLines(for: stats) { print(line) }
    print("--- right-click menu")
    let noop = Selector(("noop"))
    for row in StatsProvider.rows(for: stats, optimise: noop, open: noop, log: noop, quit: noop, freeMore: noop) {
        switch row {
        case .separator: print("---")
        case .header(let text): print("# \(text)")
        case .info(let text): print("  \(text)")
        case .action(let text, _): print("> \(text)")
        }
    }
    exit(0)
}

// --render-menubar <dir>: write PNGs of the menu bar card (first click, details, dark and light) and the icon.
if let at = CommandLine.arguments.firstIndex(of: "--render-menubar"), at + 1 < CommandLine.arguments.count {
    let port = Int(ProcessInfo.processInfo.environment["ODYSSEUS_PORT"] ?? "") ?? 7860
    let sampler = SystemSampler()
    _ = sampler.cpuPercent()
    Thread.sleep(forTimeInterval: 0.4)
    let live = StatsProvider.collect(port: port, repoDir: resolveRepoDir(), sampler: sampler)
    do {
        try MainActor.assumeIsolated { try MenuBarPreview.render(to: CommandLine.arguments[at + 1], live: live) }
        print("wrote previews to \(CommandLine.arguments[at + 1])")
        exit(0)
    } catch {
        print("render failed: \(error)")
        exit(1)
    }
}

if CommandLine.arguments.contains("--menubar-unload-all") {
    print("asked to unload \(StatsProvider.unloadAll()) model(s)")
    exit(0)
}

// --menubar-optimise: what the card's "Optimise memory" does (server endpoint, else direct unload).
if CommandLine.arguments.contains("--menubar-optimise") {
    let port = Int(ProcessInfo.processInfo.environment["ODYSSEUS_PORT"] ?? "") ?? 7860
    print(StatsProvider.optimise(port: port))
    exit(0)
}

// --menubar-heavy-apps: the apps "Free more memory" would offer to quit (name and footprint), without any UI.
if CommandLine.arguments.contains("--menubar-heavy-apps") {
    let apps = MemoryFreer.heavyApps()
    for heavy in apps { print(String(format: "%5.1f GB  %@", heavy.gb, heavy.name)) }
    print(apps.isEmpty ? "nothing to offer" : "\(apps.count) app(s) offered")
    exit(0)
}

let app = OdysseusApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
