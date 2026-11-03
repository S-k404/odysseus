//
// main.swift
// Entry point for the Odysseus Mac app. `--dump-menubar` prints what the menu bar
// item would show (stats and menu rows) and exits, so it can be checked without a UI;
// `--menubar-unload-all` does what the menu's "Unload all models" does.
//

import Cocoa

if CommandLine.arguments.contains("--dump-menubar") {
    let port = Int(ProcessInfo.processInfo.environment["ODYSSEUS_PORT"] ?? "") ?? 7860
    let stats = StatsProvider.collect(port: port, repoDir: resolveRepoDir())
    print("title: [\(StatsProvider.title(for: stats))]")
    let noop = Selector(("noop"))
    for row in StatsProvider.rows(for: stats, unload: noop, open: noop, log: noop, quit: noop) {
        switch row {
        case .separator: print("---")
        case .header(let text): print("# \(text)")
        case .info(let text): print("  \(text)")
        case .action(let text, _): print("> \(text)")
        }
    }
    exit(0)
}

if CommandLine.arguments.contains("--menubar-unload-all") {
    print("asked to unload \(StatsProvider.unloadAll()) model(s)")
    exit(0)
}

let app = OdysseusApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
