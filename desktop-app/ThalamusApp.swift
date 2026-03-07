import Cocoa
import WebKit

let THALAMUS_PORT: Int = 3013
let UI_PORT: Int = 3014

class AppDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var webView: WKWebView!
    var serverProcess: Process?
    var uiProcess: Process?

    func applicationDidFinishLaunching(_ notification: Notification) {
        startThalamusServer()
        startUIServer()

        let config = WKWebViewConfiguration()
        config.preferences.setValue(true, forKey: "developerExtrasEnabled")

        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self

        let screenSize = NSScreen.main?.frame.size ?? NSSize(width: 1440, height: 900)
        let winW: CGFloat = 440
        let winH: CGFloat = 600
        let x = (screenSize.width - winW) / 2
        let y = (screenSize.height - winH) / 2

        window = NSWindow(
            contentRect: NSRect(x: x, y: y, width: winW, height: winH),
            styleMask: [.titled, .closable, .miniaturizable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        window.title = "Thalamus"
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .hidden
        window.backgroundColor = NSColor(red: 15/255, green: 15/255, blue: 19/255, alpha: 1)
        window.contentView = webView
        window.isReleasedWhenClosed = false

        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
            self.loadUI()
        }

        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func loadUI() {
        let url = URL(string: "http://127.0.0.1:\(UI_PORT)")!
        webView.load(URLRequest(url: url))
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return true
    }

    func applicationWillTerminate(_ notification: Notification) {
        serverProcess?.terminate()
        uiProcess?.terminate()
    }

    func findPython() -> String {
        let base = thalamusDir()
        let candidates = [
            "\(base)/.venv/bin/python3",
            "\(base)/venv/bin/python3",
            "/opt/homebrew/bin/python3",
            "/usr/local/bin/python3",
            "/usr/bin/python3",
        ]
        for p in candidates {
            if FileManager.default.isExecutableFile(atPath: p) { return p }
        }
        return "/usr/bin/python3"
    }

    func thalamusDir() -> String {
        if let envDir = ProcessInfo.processInfo.environment["THALAMUS_DIR"] {
            return envDir
        }
        let bundleRes = Bundle.main.resourcePath ?? ""

        // Read path from config file written by build.sh
        let confPath = "\(bundleRes)/thalamus_path.conf"
        if let confData = FileManager.default.contents(atPath: confPath),
           let confStr = String(data: confData, encoding: .utf8) {
            let dir = confStr.trimmingCharacters(in: .whitespacesAndNewlines)
            if FileManager.default.fileExists(atPath: "\(dir)/server.py") {
                return dir
            }
        }

        let bundled = "\(bundleRes)/thalamus-py"
        if FileManager.default.fileExists(atPath: "\(bundled)/server.py") {
            return bundled
        }
        return FileManager.default.currentDirectoryPath
    }

    func startThalamusServer() {
        let py = findPython()
        let dir = thalamusDir()
        guard FileManager.default.fileExists(atPath: "\(dir)/server.py") else {
            print("ERROR: server.py not found in \(dir)")
            return
        }

        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: py)
        proc.arguments = ["server.py"]
        proc.currentDirectoryURL = URL(fileURLWithPath: dir)
        proc.environment = ProcessInfo.processInfo.environment
        proc.environment?["PORT"] = String(THALAMUS_PORT)

        let pipe = Pipe()
        proc.standardOutput = pipe
        proc.standardError = pipe

        pipe.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            if let str = String(data: data, encoding: .utf8), !str.isEmpty {
                print("[thalamus] \(str.trimmingCharacters(in: .whitespacesAndNewlines))")
            }
        }

        do {
            try proc.run()
            serverProcess = proc
            print("thalamus-py started (pid: \(proc.processIdentifier))")
        } catch {
            print("Failed to start thalamus: \(error)")
        }
    }

    func startUIServer() {
        let py = findPython()
        let scriptDir = Bundle.main.resourcePath ?? URL(fileURLWithPath: #file).deletingLastPathComponent().path
        let launcherPath: String

        let bundledLauncher = "\(scriptDir)/launcher_ui.py"
        let devLauncher = URL(fileURLWithPath: #file).deletingLastPathComponent().appendingPathComponent("launcher_ui.py").path

        if FileManager.default.fileExists(atPath: bundledLauncher) {
            launcherPath = bundledLauncher
        } else if FileManager.default.fileExists(atPath: devLauncher) {
            launcherPath = devLauncher
        } else {
            print("ERROR: launcher_ui.py not found")
            return
        }

        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: py)
        proc.arguments = [launcherPath]
        proc.environment = ProcessInfo.processInfo.environment
        proc.environment?["THALAMUS_PORT"] = String(THALAMUS_PORT)
        proc.environment?["UI_PORT"] = String(UI_PORT)

        do {
            try proc.run()
            uiProcess = proc
            print("UI server started on port \(UI_PORT)")
        } catch {
            print("Failed to start UI server: \(error)")
        }
    }
}

extension AppDelegate: WKNavigationDelegate {
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
            self.loadUI()
        }
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
            self.loadUI()
        }
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if let url = navigationAction.request.url,
           url.host != "127.0.0.1" && url.host != "localhost" {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
            return
        }
        decisionHandler(.allow)
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
