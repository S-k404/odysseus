//
// OdysseusApp.swift
// Native macOS Desktop Application for Odysseus (Apple Silicon & Intel)
// Provides a native Cocoa WKWebView window, automatic local server lifecycle management,
// native macOS menu bar, and Claude Desktop-style window chrome.
//

import Cocoa
import WebKit

class OdysseusApplication: NSApplication {
    // Custom subclass to support standard first-responder keyboard events
}

class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate {
    var window: NSWindow!
    var webView: WKWebView!
    var splashView: NSView!
    var statusLabel: NSTextField!
    var spinner: NSProgressIndicator!
    var serverProcess: Process?
    var childWindows: [NSWindow] = []
    var downloadWindows: [ObjectIdentifier: NSWindow] = [:]
    
    let defaultPort = 7860
    var port: Int = 7860
    var appURL: URL {
        return URL(string: "http://127.0.0.1:\(port)")!
    }
    
    var repoDir: String {
        if let envRepo = ProcessInfo.processInfo.environment["ODYSSEUS_REPO_DIR"] {
            return envRepo
        }
        return "/Users/shamit/Documents/Docker/Odysseus"
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        if let envPortStr = ProcessInfo.processInfo.environment["ODYSSEUS_PORT"],
           let envPort = Int(envPortStr) {
            self.port = envPort
        }

        setupMenuBar()
        setupWindow()
        checkOrStartServer()
    }

    func setupWindow() {
        let screenRect = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        let winWidth: CGFloat = min(1320, screenRect.width * 0.9)
        let winHeight: CGFloat = min(880, screenRect.height * 0.9)
        let winRect = NSRect(
            x: (screenRect.width - winWidth) / 2 + screenRect.origin.x,
            y: (screenRect.height - winHeight) / 2 + screenRect.origin.y,
            width: winWidth,
            height: winHeight
        )

        window = NSWindow(
            contentRect: winRect,
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        window.title = "Odysseus"
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .hidden
        window.backgroundColor = NSColor(red: 0.12, green: 0.12, blue: 0.11, alpha: 1.0)
        window.minSize = NSSize(width: 860, height: 600)
        window.isReleasedWhenClosed = false

        // WKWebView Configuration
        let config = WKWebViewConfiguration()
        config.preferences.setValue(true, forKey: "developerExtrasEnabled")
        
        // Allow local network and cookies
        let pagePrefs = WKWebpagePreferences()
        pagePrefs.allowsContentJavaScript = true
        config.defaultWebpagePreferences = pagePrefs

        webView = WKWebView(frame: window.contentView!.bounds, configuration: config)
        webView.autoresizingMask = [.width, .height]
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.setValue(false, forKey: "drawsBackground") // Transparent background until loaded

        // Splash / Loading View
        splashView = NSView(frame: window.contentView!.bounds)
        splashView.autoresizingMask = [.width, .height]
        splashView.wantsLayer = true
        splashView.layer?.backgroundColor = NSColor(red: 0.12, green: 0.12, blue: 0.11, alpha: 1.0).cgColor

        // Brand Label
        let titleLabel = NSTextField(labelWithString: "Odysseus")
        titleLabel.font = NSFont.systemFont(ofSize: 32, weight: .bold)
        titleLabel.textColor = NSColor(red: 0.85, green: 0.47, blue: 0.34, alpha: 1.0) // Claude terracotta
        titleLabel.alignment = .center
        titleLabel.frame = NSRect(x: 0, y: winHeight / 2 + 30, width: winWidth, height: 44)
        titleLabel.autoresizingMask = [.width, .minYMargin, .maxYMargin]
        splashView.addSubview(titleLabel)

        // Status Label
        // Wrapping, so a startup error (e.g. data folder already in use) fits.
        statusLabel = NSTextField(wrappingLabelWithString: "Starting local workspace & models...")
        statusLabel.font = NSFont.systemFont(ofSize: 13, weight: .regular)
        statusLabel.textColor = NSColor(white: 0.7, alpha: 1.0)
        statusLabel.alignment = .center
        statusLabel.isSelectable = true
        statusLabel.frame = NSRect(x: 60, y: winHeight / 2 - 46, width: winWidth - 120, height: 60)
        statusLabel.autoresizingMask = [.width, .minYMargin, .maxYMargin]
        splashView.addSubview(statusLabel)

        // Spinner
        spinner = NSProgressIndicator(frame: NSRect(x: (winWidth - 24) / 2, y: winHeight / 2 - 78, width: 24, height: 24))
        spinner.style = .spinning
        spinner.controlSize = .small
        spinner.autoresizingMask = [.minXMargin, .maxXMargin, .minYMargin, .maxYMargin]
        spinner.startAnimation(nil)
        splashView.addSubview(spinner)

        window.contentView?.addSubview(webView)
        window.contentView?.addSubview(splashView)

        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func checkOrStartServer() {
        // First check if server is already running on port
        probeServer { [weak self] running in
            guard let self = self else { return }
            if running {
                DispatchQueue.main.async {
                    self.loadAppUI()
                }
            } else {
                DispatchQueue.main.async {
                    self.spawnBackendServer()
                }
            }
        }
    }

    func probeServer(completion: @escaping (Bool) -> Void) {
        var req = URLRequest(url: self.appURL)
        req.timeoutInterval = 1.0
        req.httpMethod = "HEAD"
        let task = URLSession.shared.dataTask(with: req) { _, response, error in
            if let http = response as? HTTPURLResponse, (200...499).contains(http.statusCode) {
                completion(true)
            } else {
                completion(false)
            }
        }
        task.resume()
    }

    func spawnBackendServer() {
        let venvPy = "\(repoDir)/.venv/bin/python"
        let fallbackPy = "\(repoDir)/venv/bin/python"
        let pythonPath = FileManager.default.fileExists(atPath: venvPy) ? venvPy : fallbackPy

        guard FileManager.default.fileExists(atPath: pythonPath) else {
            statusLabel.stringValue = "Setup required: Python virtual environment not found in \(repoDir)"
            spinner.stopAnimation(nil)
            return
        }

        statusLabel.stringValue = "Launching Odysseus local engine (port \(port))..."
        
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: pythonPath)
        proc.arguments = ["-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "\(port)"]
        proc.currentDirectoryURL = URL(fileURLWithPath: repoDir)
        
        var env = ProcessInfo.processInfo.environment
        env["APP_PORT"] = "\(port)"
        env["PYTHONPATH"] = repoDir
        // Apps launched from Finder/Dock get a bare PATH, so MCP servers that
        // run through docker, npx, or uvx would fail to start.
        let toolPaths = ["/opt/homebrew/bin", "/usr/local/bin", "\(NSHomeDirectory())/.local/bin"]
        env["PATH"] = (toolPaths + [env["PATH"] ?? "/usr/bin:/bin:/usr/sbin:/sbin"]).joined(separator: ":")
        proc.environment = env

        // Send server output to a log file. An unread Pipe fills up (~64 KB)
        // and then blocks the server on its next log write.
        let logPath = "\(repoDir)/logs/odysseus-app.log"
        try? FileManager.default.createDirectory(atPath: "\(repoDir)/logs", withIntermediateDirectories: true)
        // O_APPEND, not seek-to-end: when the app is quit and reopened, the old
        // server is still shutting down and writing to this file. With separate
        // offsets the two servers overwrote each other's lines, which hid the
        // new server's error from the startup screen.
        let logFD = open(logPath, O_WRONLY | O_APPEND | O_CREAT, 0o644)
        if logFD >= 0 {
            let log = FileHandle(fileDescriptor: logFD, closeOnDealloc: true)
            proc.standardOutput = log
            proc.standardError = log
        } else {
            proc.standardOutput = FileHandle.nullDevice
            proc.standardError = FileHandle.nullDevice
        }

        do {
            try proc.run()
            self.serverProcess = proc
            
            // Poll for server readiness
            pollServerReady(attemptsLeft: 90)
        } catch {
            statusLabel.stringValue = "Failed to launch server: \(error.localizedDescription)"
            spinner.stopAnimation(nil)
        }
    }

    func pollServerReady(attemptsLeft: Int) {
        if let proc = serverProcess, !proc.isRunning {
            DispatchQueue.main.async { self.showServerStopped() }
            return
        }
        if attemptsLeft <= 0 {
            DispatchQueue.main.async {
                self.statusLabel.stringValue = "Server took too long to respond. See \(self.repoDir)/logs/odysseus-app.log"
                self.spinner.stopAnimation(nil)
            }
            return
        }

        probeServer { [weak self] ready in
            guard let self = self else { return }
            if ready {
                DispatchQueue.main.async {
                    self.loadAppUI()
                }
            } else {
                DispatchQueue.global().asyncAfter(deadline: .now() + 1.0) {
                    self.pollServerReady(attemptsLeft: attemptsLeft - 1)
                }
            }
        }
    }

    /// The server exited during startup: show why, from the end of its log.
    /// The usual cause is another Odysseus server (the Docker copy) already
    /// using the data folder.
    func showServerStopped() {
        let logPath = "\(repoDir)/logs/odysseus-app.log"
        var reason = "The Odysseus server stopped during startup."
        if let handle = FileHandle(forReadingAtPath: logPath) {
            let size = handle.seekToEndOfFile()
            handle.seek(toFileOffset: size > 65536 ? size - 65536 : 0)
            let lines = String(decoding: handle.readDataToEndOfFile(), as: UTF8.self).split(separator: "\n")
            handle.closeFile()
            if let line = lines.last(where: { $0.contains("DataDirInUse: ") }),
               let range = line.range(of: "DataDirInUse: ") {
                reason = String(line[range.upperBound...])
            }
        }
        statusLabel.stringValue = "\(reason)\nLog: \(logPath)"
        spinner.stopAnimation(nil)
        spinner.isHidden = true
    }

    func loadAppUI() {
        statusLabel.stringValue = "Connecting..."
        webView.load(URLRequest(url: self.appURL))
    }

    // MARK: - WKNavigationDelegate

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard webView === self.webView else { return }
        // Fade out splash
        NSAnimationContext.runAnimationGroup({ context in
            context.duration = 0.35
            splashView.animator().alphaValue = 0.0
        }, completionHandler: { [weak self] in
            self?.splashView.isHidden = true
            self?.spinner.stopAnimation(nil)
        })
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        guard webView === self.webView else { return }
        statusLabel.stringValue = "Connection error: \(error.localizedDescription)"
    }

    /// Pages served by the local Odysseus server (plus blank/blob/data
    /// documents it creates) stay in the app; everything else is external.
    func isAppURL(_ url: URL?) -> Bool {
        guard let url = url, let scheme = url.scheme?.lowercased() else { return true }
        if ["about", "blob", "data"].contains(scheme) { return true }
        guard scheme == "http" || scheme == "https" else { return false }
        return url.host == "127.0.0.1" || url.host == "localhost"
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if #available(macOS 11.3, *), navigationAction.shouldPerformDownload {
            decisionHandler(.download)
            return
        }
        if navigationAction.targetFrame?.isMainFrame == true,
           navigationAction.navigationType == .linkActivated,
           let url = navigationAction.request.url, !isAppURL(url) {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
            return
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationResponse: WKNavigationResponse, decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        let disposition = (navigationResponse.response as? HTTPURLResponse)?.value(forHTTPHeaderField: "Content-Disposition") ?? ""
        if #available(macOS 11.3, *),
           !navigationResponse.canShowMIMEType || disposition.lowercased().hasPrefix("attachment") {
            decisionHandler(.download)
            return
        }
        decisionHandler(.allow)
    }

    // MARK: - WKUIDelegate (JS dialogs, file picker, new windows)

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.addButton(withTitle: "OK")
        alert.beginSheetModal(for: webView.window ?? window) { _ in completionHandler() }
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.addButton(withTitle: "OK")
        alert.addButton(withTitle: "Cancel")
        alert.beginSheetModal(for: webView.window ?? window) { completionHandler($0 == .alertFirstButtonReturn) }
    }

    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String, defaultText: String?, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (String?) -> Void) {
        let alert = NSAlert()
        alert.messageText = prompt
        alert.addButton(withTitle: "OK")
        alert.addButton(withTitle: "Cancel")
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 300, height: 24))
        field.stringValue = defaultText ?? ""
        alert.accessoryView = field
        alert.window.initialFirstResponder = field
        alert.beginSheetModal(for: webView.window ?? window) {
            completionHandler($0 == .alertFirstButtonReturn ? field.stringValue : nil)
        }
    }

    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = parameters.allowsDirectories
        panel.canChooseFiles = true
        panel.beginSheetModal(for: webView.window ?? window) { completionHandler($0 == .OK ? panel.urls : nil) }
    }

    // target="_blank" / window.open(): external sites go to the default
    // browser; Odysseus pages (reports, exports, print views) get an app
    // window that shares the login session.
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = navigationAction.request.url, !isAppURL(url) {
            NSWorkspace.shared.open(url)
            return nil
        }
        let size = NSSize(width: CGFloat(truncating: windowFeatures.width ?? 960),
                          height: CGFloat(truncating: windowFeatures.height ?? 720))
        let child = NSWindow(contentRect: NSRect(origin: .zero, size: size),
                             styleMask: [.titled, .closable, .miniaturizable, .resizable],
                             backing: .buffered, defer: false)
        child.isReleasedWhenClosed = false
        child.title = "Odysseus"
        child.center()
        let childView = WKWebView(frame: child.contentView!.bounds, configuration: configuration)
        childView.autoresizingMask = [.width, .height]
        childView.navigationDelegate = self
        childView.uiDelegate = self
        child.contentView?.addSubview(childView)
        child.makeKeyAndOrderFront(nil)
        childWindows.append(child)
        NotificationCenter.default.addObserver(forName: NSWindow.willCloseNotification, object: child, queue: .main) { [weak self] note in
            self?.childWindows.removeAll { $0 === (note.object as? NSWindow) }
        }
        return childView
    }

    func webViewDidClose(_ webView: WKWebView) {
        if webView !== self.webView { webView.window?.close() }
    }

    func uniqueDownloadURL(for name: String) -> URL {
        let dir = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask)[0]
        let base = (name as NSString).deletingPathExtension
        let ext = (name as NSString).pathExtension
        var url = dir.appendingPathComponent(name)
        var n = 1
        while FileManager.default.fileExists(atPath: url.path) {
            url = dir.appendingPathComponent(ext.isEmpty ? "\(base) (\(n))" : "\(base) (\(n)).\(ext)")
            n += 1
        }
        return url
    }

    // MARK: - Menu Bar & Actions

    func setupMenuBar() {
        let mainMenu = NSMenu()
        
        // App Menu
        let appMenuItem = NSMenuItem()
        let appMenu = NSMenu(title: "Odysseus")
        appMenu.addItem(withTitle: "About Odysseus", action: #selector(openAbout), keyEquivalent: "")
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(withTitle: "Preferences...", action: #selector(openSettings), keyEquivalent: ",")
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(withTitle: "Hide Odysseus", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(withTitle: "Hide Others", action: #selector(NSApplication.hideOtherApplications(_:)), keyEquivalent: "h").keyEquivalentModifierMask = [.command, .option]
        appMenu.addItem(withTitle: "Show All", action: #selector(NSApplication.unhideAllApplications(_:)), keyEquivalent: "")
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(withTitle: "Quit Odysseus", action: #selector(quitApp), keyEquivalent: "q")
        appMenuItem.submenu = appMenu
        mainMenu.addItem(appMenuItem)

        // File Menu
        let fileMenuItem = NSMenuItem()
        let fileMenu = NSMenu(title: "File")
        fileMenu.addItem(withTitle: "New Chat", action: #selector(newChat), keyEquivalent: "n")
        fileMenu.addItem(withTitle: "Search Conversations", action: #selector(searchChats), keyEquivalent: "k")
        fileMenu.addItem(NSMenuItem.separator())
        fileMenu.addItem(withTitle: "Close Window", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        fileMenuItem.submenu = fileMenu
        mainMenu.addItem(fileMenuItem)

        // Edit Menu
        let editMenuItem = NSMenuItem()
        let editMenu = NSMenu(title: "Edit")
        editMenu.addItem(withTitle: "Undo", action: #selector(UndoManager.undo), keyEquivalent: "z")
        editMenu.addItem(withTitle: "Redo", action: #selector(UndoManager.redo), keyEquivalent: "Z")
        editMenu.addItem(NSMenuItem.separator())
        editMenu.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editMenuItem.submenu = editMenu
        mainMenu.addItem(editMenuItem)

        // View Menu
        let viewMenuItem = NSMenuItem()
        let viewMenu = NSMenu(title: "View")
        viewMenu.addItem(withTitle: "Connectors & Extensions", action: #selector(openConnectors), keyEquivalent: "C")
        viewMenu.addItem(withTitle: "Reload", action: #selector(reloadUI), keyEquivalent: "r")
        viewMenu.addItem(NSMenuItem.separator())
        viewMenu.addItem(withTitle: "Toggle Full Screen", action: #selector(NSWindow.toggleFullScreen(_:)), keyEquivalent: "f").keyEquivalentModifierMask = [.command, .control]
        viewMenu.addItem(withTitle: "Developer Tools", action: #selector(toggleDevTools), keyEquivalent: "i").keyEquivalentModifierMask = [.command, .option]
        viewMenuItem.submenu = viewMenu
        mainMenu.addItem(viewMenuItem)

        NSApp.mainMenu = mainMenu
    }

    @objc func openAbout() {
        let alert = NSAlert()
        alert.messageText = "Odysseus for macOS"
        alert.informativeText = "A self-hosted AI workspace with full local tools, skills, and Claude Desktop Connectors."
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }

    @objc func newChat() {
        showMainWindow()
        webView.evaluateJavaScript("document.getElementById('sidebar-new-chat-btn')?.click();", completionHandler: nil)
    }

    @objc func searchChats() {
        webView.evaluateJavaScript("document.getElementById('sidebar-search-btn')?.click();", completionHandler: nil)
    }

    @objc func openSettings() {
        showMainWindow()
        webView.evaluateJavaScript("document.getElementById('user-bar-settings')?.click();", completionHandler: nil)
    }

    @objc func openConnectors() {
        webView.evaluateJavaScript("document.getElementById('tool-connectors-btn')?.click();", completionHandler: nil)
    }

    @objc func reloadUI() {
        webView.reload()
    }

    @objc func toggleDevTools() {
        // macOS WebKit Web Inspector toggle
        webView.evaluateJavaScript("console.log('Opening Inspector...');", completionHandler: nil)
    }

    @objc func quitApp() {
        NSApp.terminate(nil)
    }

    // Closing the window keeps the app (and its server) running like Claude
    // Desktop; clicking the Dock icon brings the window back.
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag { showMainWindow() }
        return true
    }

    func showMainWindow() {
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationWillTerminate(_ notification: Notification) {
        if let proc = serverProcess, proc.isRunning {
            proc.terminate()
        }
    }
}

// Downloads (export buttons, attachments, <a download>) land in ~/Downloads.
@available(macOS 11.3, *)
extension AppDelegate: WKDownloadDelegate {
    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
        trackDownload(download, from: webView)
    }

    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) {
        trackDownload(download, from: webView)
    }

    func trackDownload(_ download: WKDownload, from webView: WKWebView) {
        download.delegate = self
        // A window opened only to fetch a file would otherwise sit there blank.
        if webView !== self.webView, let child = webView.window, webView.url == nil || webView.backForwardList.currentItem == nil {
            child.orderOut(nil)
            downloadWindows[ObjectIdentifier(download)] = child
        }
    }

    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        completionHandler(uniqueDownloadURL(for: suggestedFilename))
    }

    func downloadDidFinish(_ download: WKDownload) {
        downloadWindows.removeValue(forKey: ObjectIdentifier(download))?.close()
        NSApp.requestUserAttention(.informationalRequest)
    }

    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        downloadWindows.removeValue(forKey: ObjectIdentifier(download))?.close()
        let alert = NSAlert()
        alert.messageText = "Download failed"
        alert.informativeText = error.localizedDescription
        alert.runModal()
    }
}

// Main Entry Point
let app = OdysseusApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()

