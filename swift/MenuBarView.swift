//
// MenuBarView.swift
// The look of the Odysseus menu bar item: the animated icon, and the card that opens on click.
// First click: status, loaded model, memory/GPU/CPU at a glance. "Details" adds the organised view.
//

import Cocoa
import SwiftUI

// MARK: - Icon

/// A ring that fills with memory in use, a core, and a moon that orbits faster the busier the GPU is.
enum MenuBarIcon {
    enum Mode {
        case off, idle, loaded, busy, warning, critical

        var revolutionsPerSecond: Double {
            switch self {
            case .off: return 0
            case .idle: return 0.22
            case .loaded: return 0.5
            case .busy: return 1.5
            case .warning: return 0.9
            case .critical: return 1.3
            }
        }

        var framesPerSecond: Double {
            switch self {
            case .off: return 1
            case .idle: return 12
            case .loaded: return 15
            case .busy, .warning, .critical: return 24
            }
        }
    }

    /// `ink` is for previews drawn on a known background; the live icon leaves it nil so the
    /// system tints it (template), except warning and critical, which keep their own colour.
    static func image(angle: Double, pulse: Double, memory: Double, mode: Mode, size: CGFloat = 18, ink: NSColor? = nil) -> NSImage {
        let image = NSImage(size: NSSize(width: size, height: size), flipped: false) { rect in
            let s = size / 18
            let center = NSPoint(x: rect.midX, y: rect.midY)
            let base: NSColor
            switch mode {
            case .critical: base = .systemRed
            case .warning: base = .systemOrange
            default: base = ink ?? .black
            }
            func circle(_ radius: CGFloat) -> NSBezierPath {
                NSBezierPath(ovalIn: NSRect(x: center.x - radius, y: center.y - radius, width: radius * 2, height: radius * 2))
            }

            // Ring: faint track, bright arc for memory in use, clockwise from the top.
            let ringRadius = 7.4 * s
            let track = circle(ringRadius)
            track.lineWidth = 1.3 * s
            base.withAlphaComponent(mode == .off ? 0.28 : 0.34).setStroke()
            track.stroke()
            if mode != .off && memory > 0.01 {
                let arc = NSBezierPath()
                arc.appendArc(withCenter: center, radius: ringRadius, startAngle: 90,
                              endAngle: 90 - 360 * CGFloat(min(memory, 1)), clockwise: true)
                arc.lineWidth = 1.9 * s
                arc.lineCapStyle = .round
                base.setStroke()
                arc.stroke()
            }

            // Core: hollow when nothing is loaded, solid when a model is, breathing when busy.
            let breathing = (mode == .busy || mode == .warning || mode == .critical) ? CGFloat(pulse) * 0.7 * s : 0
            switch mode {
            case .off:
                let core = circle(2.0 * s)
                core.lineWidth = 1.1 * s
                base.withAlphaComponent(0.28).setStroke()
                core.stroke()
            case .idle:
                let core = circle(2.0 * s)
                core.lineWidth = 1.2 * s
                base.withAlphaComponent(0.8).setStroke()
                core.stroke()
            default:
                base.setFill()
                circle(2.2 * s + breathing).fill()
            }

            // Moon: a small dot on the inner orbit.
            if mode != .off {
                let orbit = 4.6 * s
                let a = CGFloat(angle)
                let moon = NSPoint(x: center.x + orbit * cos(a), y: center.y + orbit * sin(a))
                base.setFill()
                NSBezierPath(ovalIn: NSRect(x: moon.x - 1.15 * s, y: moon.y - 1.15 * s, width: 2.3 * s, height: 2.3 * s)).fill()
            }
            return true
        }
        image.isTemplate = ink == nil && mode != .warning && mode != .critical
        return image
    }
}

// MARK: - Card pieces

private let accent = Color(red: 0.851, green: 0.467, blue: 0.341)

private func pressureColor(_ memory: MemoryStats?) -> Color {
    guard let m = memory else { return .secondary }
    return m.pressure >= 4 ? .red : (m.pressure >= 2 ? .orange : .green)
}

private struct HeightKey: PreferenceKey {
    static var defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value = max(value, nextValue()) }
}

private struct Card<Content: View>: View {
    let content: Content
    init(@ViewBuilder _ content: () -> Content) { self.content = content() }

    var body: some View {
        content
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(Color.primary.opacity(0.06)))
            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(Color.primary.opacity(0.07), lineWidth: 1))
    }
}

private struct Bar: View {
    let fraction: Double
    let color: Color
    var height: CGFloat = 4

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(Color.primary.opacity(0.12))
                Capsule().fill(color).frame(width: max(height, geo.size.width * CGFloat(min(max(fraction, 0), 1))))
            }
        }
        .frame(height: height)
    }
}

private struct Sparkline: View {
    let values: [Double]  // 0...100, newest last
    let color: Color

    var body: some View {
        GeometryReader { geo in
            let points = Self.points(values, in: geo.size)
            ZStack {
                Path { p in
                    guard let first = points.first, let last = points.last else { return }
                    p.move(to: CGPoint(x: first.x, y: geo.size.height))
                    points.forEach { p.addLine(to: $0) }
                    p.addLine(to: CGPoint(x: last.x, y: geo.size.height))
                    p.closeSubpath()
                }
                .fill(LinearGradient(colors: [color.opacity(0.32), color.opacity(0.02)], startPoint: .top, endPoint: .bottom))
                Path { p in
                    guard let first = points.first else { return }
                    p.move(to: first)
                    points.dropFirst().forEach { p.addLine(to: $0) }
                }
                .stroke(color, style: StrokeStyle(lineWidth: 1.4, lineCap: .round, lineJoin: .round))
            }
        }
        .frame(height: 34)
        .overlay(Rectangle().fill(Color.primary.opacity(0.1)).frame(height: 1), alignment: .bottom)
    }

    static func points(_ values: [Double], in size: CGSize) -> [CGPoint] {
        guard values.count > 1 else { return [] }
        let step = size.width / CGFloat(MenuBarModel.historyLength - 1)
        let start = size.width - step * CGFloat(values.count - 1)
        return values.enumerated().map { index, value in
            CGPoint(x: start + step * CGFloat(index), y: size.height - size.height * CGFloat(min(max(value, 0), 100) / 100))
        }
    }
}

private struct Pill: View {
    let text: String
    let color: Color

    var body: some View {
        HStack(spacing: 5) {
            Circle().fill(color).frame(width: 6, height: 6)
            Text(text).font(.system(size: 11, weight: .medium))
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 3)
        .background(Capsule().fill(color.opacity(0.16)))
    }
}

private struct Tile: View {
    let title: String
    let value: String
    let caption: String
    let fraction: Double
    let color: Color

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 3) {
                Text(title.uppercased()).font(.system(size: 9.5, weight: .semibold)).kerning(0.6).foregroundColor(.secondary)
                Text(value).font(.system(size: 21, weight: .semibold, design: .rounded)).lineLimit(1).minimumScaleFactor(0.7)
                Text(caption).font(.system(size: 10.5)).foregroundColor(.secondary).lineLimit(1)
                Bar(fraction: fraction, color: color).padding(.top, 2)
            }
        }
    }
}

private struct SectionTitle: View {
    let icon: String
    let title: String

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: icon).font(.system(size: 11, weight: .medium)).foregroundColor(.secondary)
            Text(title).font(.system(size: 12, weight: .semibold))
            Spacer()
        }
    }
}

private struct KeyValue: View {
    let key: String
    let value: String

    var body: some View {
        HStack {
            Text(key).foregroundColor(.secondary)
            Spacer()
            Text(value).monospacedDigit()
        }
        .font(.system(size: 12))
    }
}

private struct PillButtonStyle: ButtonStyle {
    var primary = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 12, weight: .medium))
            .lineLimit(1)
            .fixedSize()
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .foregroundColor(primary ? .white : .primary)
            .background(Capsule().fill(primary ? accent : Color.primary.opacity(0.10)))
            .opacity(configuration.isPressed ? 0.7 : 1)
    }
}

private struct Orb: View {
    let mode: MenuBarIcon.Mode
    let memory: Double

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 24.0)) { context in
            let t = context.date.timeIntervalSinceReferenceDate
            Image(nsImage: MenuBarIcon.image(angle: t * mode.revolutionsPerSecond * 2 * .pi, pulse: (sin(t * 5) + 1) / 2,
                                             memory: memory, mode: mode, size: 30))
                .renderingMode(.template)
                .foregroundColor(accent)
        }
        .frame(width: 30, height: 30)
    }
}

// MARK: - Card

struct MenuBarView: View {
    static let width: CGFloat = 340

    @ObservedObject var model: MenuBarModel
    let actions: MenuBarActions
    var onHeight: (CGFloat) -> Void = { _ in }

    private var stats: MenuStats { model.stats }

    var body: some View {
        VStack(spacing: 10) {
            header
            modelCard
            tiles
            buttons
            if model.expanded { details }
        }
        .padding(14)
        .frame(width: Self.width)
        .fixedSize(horizontal: false, vertical: true)
        .background(GeometryReader { Color.clear.preference(key: HeightKey.self, value: $0.size.height) })
        .onPreferenceChange(HeightKey.self) { onHeight($0) }
    }

    // MARK: First click

    private var header: some View {
        HStack(spacing: 10) {
            Orb(mode: stats.iconMode, memory: stats.memory?.fraction ?? 0)
            VStack(alignment: .leading, spacing: 1) {
                Text("Odysseus").font(.system(size: 15, weight: .semibold))
                Text(verbatim: stats.serverUp ? "Running on :\(stats.port)" : "Server not running")
                    .font(.system(size: 11)).foregroundColor(.secondary)
            }
            Spacer()
            statusPill
        }
    }

    private var statusPill: some View {
        switch stats.iconMode {
        case .off: return Pill(text: "Offline", color: .gray)
        case .idle: return Pill(text: "Idle", color: .green)
        case .loaded: return Pill(text: "Ready", color: .green)
        case .busy: return Pill(text: "Working", color: accent)
        case .warning: return Pill(text: "Memory tight", color: .orange)
        case .critical: return Pill(text: "Memory critical", color: .red)
        }
    }

    private var modelCard: some View {
        Card {
            HStack(spacing: 10) {
                Image(systemName: "cube.transparent").font(.system(size: 16)).foregroundColor(accent).frame(width: 22)
                VStack(alignment: .leading, spacing: 1) {
                    Text(modelTitle).font(.system(size: 13, weight: .semibold)).lineLimit(1)
                    Text(modelCaption).font(.system(size: 11)).foregroundColor(.secondary).lineLimit(1)
                }
                Spacer()
            }
        }
    }

    private var modelTitle: String {
        if !stats.runnerUp { return "Model runner offline" }
        guard let first = stats.chatModels.first else { return "No model loaded" }
        return stats.chatModels.count > 1 ? "\(first.shortName) +\(stats.chatModels.count - 1)" : first.shortName
    }

    private var modelCaption: String {
        if !stats.runnerUp { return "Docker Model Runner isn't answering" }
        guard let first = stats.chatModels.first else { return "Loads when a chat needs it" }
        return StatsProvider.modelDetail(first)
    }

    private var tiles: some View {
        HStack(spacing: 8) {
            Tile(title: "Memory",
                 value: stats.memory.map { StatsProvider.fmt($0.usedGB).replacingOccurrences(of: " GB", with: "") } ?? "–",
                 caption: stats.memory.map { "of \(StatsProvider.fmt($0.totalGB))" } ?? "unknown",
                 fraction: stats.memory?.fraction ?? 0, color: pressureColor(stats.memory))
            Tile(title: "GPU", value: percent(stats.gpuPercent), caption: stats.gpuPercent.map { $0 >= 20 ? "working" : "idle" } ?? "n/a",
                 fraction: (stats.gpuPercent ?? 0) / 100, color: .teal)
            Tile(title: "CPU", value: percent(stats.cpuPercent), caption: "load \(String(format: "%.1f", stats.load1))",
                 fraction: (stats.cpuPercent ?? 0) / 100, color: .blue)
        }
    }

    private var buttons: some View {
        HStack(spacing: 8) {
            Button("Open Odysseus", action: actions.open).buttonStyle(PillButtonStyle(primary: true))
            Button(stats.chatModels.isEmpty ? "Unload" : "Unload (\(stats.chatModels.count))", action: actions.unload)
                .buttonStyle(PillButtonStyle())
                .disabled(stats.chatModels.isEmpty)
                .opacity(stats.chatModels.isEmpty ? 0.45 : 1)
            Spacer()
            Button {
                withAnimation(.easeInOut(duration: 0.2)) { model.expanded.toggle() }
            } label: {
                HStack(spacing: 4) {
                    Text("Details")
                    Image(systemName: model.expanded ? "chevron.up" : "chevron.down").font(.system(size: 9, weight: .bold))
                }
            }
            .buttonStyle(PillButtonStyle())
        }
    }

    // MARK: Details

    private var details: some View {
        VStack(spacing: 10) {
            modelsSection
            hardwareSection
            memorySection
            systemSection
            HStack {
                Button("Show server log", action: actions.log).buttonStyle(PillButtonStyle())
                Spacer()
                Button("Quit Odysseus", action: actions.quit).buttonStyle(PillButtonStyle())
            }
        }
    }

    private var modelsSection: some View {
        Card {
            VStack(alignment: .leading, spacing: 6) {
                SectionTitle(icon: "cube", title: "Models in memory")
                if stats.models.isEmpty {
                    Text(stats.runnerUp ? "None loaded" : "Model runner not reachable")
                        .font(.system(size: 12)).foregroundColor(.secondary)
                }
                ForEach(stats.models, id: \.name) { m in
                    HStack {
                        Text(m.shortName).font(.system(size: 12)).lineLimit(1)
                        Spacer()
                        Text(StatsProvider.modelDetail(m)).font(.system(size: 11)).foregroundColor(.secondary)
                    }
                }
            }
        }
    }

    private var hardwareSection: some View {
        Card {
            VStack(alignment: .leading, spacing: 8) {
                SectionTitle(icon: "cpu", title: "Hardware usage")
                metric("GPU", value: stats.gpuPercent, history: model.gpuHistory, color: .teal)
                metric("CPU", value: stats.cpuPercent, history: model.cpuHistory, color: .blue)
            }
        }
    }

    private func metric(_ name: String, value: Double?, history: [Double], color: Color) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(name).font(.system(size: 12, weight: .medium))
                Spacer()
                Text(percent(value)).font(.system(size: 12, weight: .semibold)).monospacedDigit()
            }
            Sparkline(values: history, color: color)
        }
    }

    private var memorySection: some View {
        Card {
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    SectionTitle(icon: "memorychip", title: "Memory")
                    if let m = stats.memory { Pill(text: m.pressureName.capitalized, color: pressureColor(m)) }
                }
                if let m = stats.memory {
                    HStack {
                        Text("\(String(format: "%.1f", m.usedGB)) / \(String(format: "%.0f", m.totalGB)) GB")
                            .font(.system(size: 12, weight: .semibold)).monospacedDigit()
                        Spacer()
                        Text("\(Int((m.fraction * 100).rounded()))% used").font(.system(size: 11)).foregroundColor(.secondary)
                    }
                    Sparkline(values: model.memoryHistory, color: pressureColor(m))
                    KeyValue(key: "Compressed", value: StatsProvider.fmt(m.compressedGB))
                    KeyValue(key: "Cached files", value: StatsProvider.fmt(m.cachedGB))
                    KeyValue(key: "Swap used", value: StatsProvider.fmt(m.swapUsedGB))
                    KeyValue(key: "Available", value: StatsProvider.fmt(m.availableGB))
                }
            }
        }
    }

    private var systemSection: some View {
        Card {
            VStack(alignment: .leading, spacing: 6) {
                SectionTitle(icon: "gauge", title: "System")
                KeyValue(key: "Thermal state", value: stats.thermal)
                KeyValue(key: "Up for", value: StatsProvider.uptimeText(stats.uptime))
                if let note = stats.guardNote {
                    Text(note).font(.system(size: 11)).foregroundColor(.orange).fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    private func percent(_ value: Double?) -> String { value.map { String(format: "%.0f%%", $0) } ?? "–" }
}

// MARK: - Preview (no screen needed)

/// `--render-menubar <dir>` writes PNGs of the card and the icon, so the look can be checked without a click.
enum MenuBarPreview {
    static var sampleStats: MenuStats {
        var s = MenuStats()
        s.serverUp = true
        s.runnerUp = true
        s.models = [ModelRow(name: "huggingface.co/unsloth/qwen3.6-35b-a3b-gguf:UD-Q3_K_S", sizeGB: 14.29, contextTokens: 16384, embedding: false)]
        s.memory = MemoryStats(totalGB: 48, usedGB: 31.9, compressedGB: 15.2, cachedGB: 11.5, swapUsedGB: 2.65, pressure: 1)
        s.cpuPercent = 25
        s.gpuPercent = 64
        s.load1 = 3.4
        s.uptime = 44 * 3600
        return s
    }

    @MainActor
    static func render(to dir: String, live: MenuStats) throws {
        try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        _ = NSApplication.shared

        func series(_ base: Double, _ swing: Double, _ seed: Double) -> [Double] {
            (0..<MenuBarModel.historyLength).map { i in
                max(0, min(100, base + swing * sin(Double(i) / 5 + seed) + swing * 0.4 * sin(Double(i) / 1.7 + seed * 2)))
            }
        }
        let busy = MenuBarModel()
        busy.stats = sampleStats
        busy.cpuHistory = series(25, 18, 0.5)
        busy.gpuHistory = series(60, 35, 1.5)
        busy.memoryHistory = series(66, 3, 0.1)

        let liveModel = MenuBarModel()
        liveModel.record(live)

        let actions = MenuBarActions(open: {}, unload: {}, log: {}, quit: {})
        for (name, model) in [("sample", busy), ("live", liveModel)] {
            for expanded in [false, true] {
                model.expanded = expanded
                for scheme in [ColorScheme.dark, .light] {
                    try write(MenuBarView(model: model, actions: actions), scheme: scheme,
                              to: "\(dir)/card-\(name)-\(expanded ? "details" : "first")-\(scheme == .dark ? "dark" : "light").png")
                }
            }
        }
        try writeIcons(to: "\(dir)/icons.png")
    }

    @MainActor
    private static func write(_ view: MenuBarView, scheme: ColorScheme, to path: String) throws {
        let background = scheme == .dark ? NSColor(white: 0.16, alpha: 1) : NSColor(white: 0.96, alpha: 1)
        let host = NSHostingView(rootView: view.environment(\.colorScheme, scheme)
            .background(Color(nsColor: background)))
        host.appearance = NSAppearance(named: scheme == .dark ? .darkAqua : .aqua)
        host.frame = NSRect(origin: .zero, size: NSSize(width: MenuBarView.width, height: 10))
        let window = NSWindow(contentRect: host.frame, styleMask: [.borderless], backing: .buffered, defer: false)
        window.contentView = host
        host.layoutSubtreeIfNeeded()
        RunLoop.current.run(until: Date().addingTimeInterval(0.35))
        let fitting = host.fittingSize
        host.frame = NSRect(origin: .zero, size: NSSize(width: MenuBarView.width, height: max(fitting.height, 40)))
        window.setContentSize(host.frame.size)
        host.layoutSubtreeIfNeeded()
        RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        guard let rep = host.bitmapImageRepForCachingDisplay(in: host.bounds) else { return }
        host.cacheDisplay(in: host.bounds, to: rep)
        try rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: path))
    }

    /// Every mode at a few phases, 8x, on dark and on light, as it would look in the menu bar.
    private static func writeIcons(to path: String) throws {
        let modes: [MenuBarIcon.Mode] = [.off, .idle, .loaded, .busy, .warning, .critical]
        let phases: [Double] = [0, 1.6, 3.2, 4.8]
        let cell = 18 * 8 + 16
        let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: cell * phases.count, pixelsHigh: cell * modes.count * 2,
                                   bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                   colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
        for (row, dark) in [true, false].enumerated() {
            for (m, mode) in modes.enumerated() {
                for (p, phase) in phases.enumerated() {
                    let origin = NSPoint(x: p * cell, y: (row * modes.count + m) * cell)
                    (dark ? NSColor(white: 0.16, alpha: 1) : NSColor(white: 0.96, alpha: 1)).setFill()
                    NSRect(x: origin.x, y: origin.y, width: CGFloat(cell), height: CGFloat(cell)).fill()
                    let image = MenuBarIcon.image(angle: phase, pulse: 0.5, memory: 0.66, mode: mode, size: 18 * 8,
                                                  ink: dark ? .white : .black)
                    image.draw(at: NSPoint(x: origin.x + 8, y: origin.y + 8), from: .zero, operation: .sourceOver, fraction: 1)
                }
            }
        }
        NSGraphicsContext.restoreGraphicsState()
        try rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: path))
    }
}
