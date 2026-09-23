import SwiftUI
import WebKit

// FORGE Mobile, native shell. The app is the live PWA at <box>/m/ in a WKWebView:
// same connector, same /api/*, zero keys on the phone. Updating the web code on the box
// updates the app — no rebuild. This file only adds what a browser tab can't do well:
// fullscreen chrome, tel:/mailto: handoff, native alert/confirm, haptics, an honest
// "can't reach the box" screen, and recovery when iOS kills the web process.

enum ForgeConfig {
    // Launch argument `-ForgeBaseURL http://localhost:7799/m/` (NSArgumentDomain) wins,
    // so a dev build can ride the SSH tunnel; otherwise the Info.plist Tailscale URL.
    static var baseURL: URL {
        let raw = UserDefaults.standard.string(forKey: "ForgeBaseURL")
            ?? (Bundle.main.object(forInfoDictionaryKey: "ForgeBaseURL") as? String)
            ?? "https://forge-reios.tail0a2dda.ts.net/m/"
        return URL(string: raw)!
    }
    static let background = UIColor(red: 0.949, green: 0.965, blue: 1.0, alpha: 1)   // #F2F6FF
    static let reloadAfterBackground: TimeInterval = 600
}

final class ForgeShell: NSObject, ObservableObject {
    enum Phase: Equatable { case loading, ready, failed(String) }
    @Published var phase: Phase = .loading

    let webView: WKWebView
    private var backgroundedAt: Date?

    override init() {
        let config = WKWebViewConfiguration()
        config.allowsInlineMediaPlayback = true
        config.websiteDataStore = .default()   // persistent: localStorage keeps the last tab
        let marker = WKUserScript(source: """
            window.FORGE_NATIVE = { platform: "ios", version: "1.0" };
            document.documentElement.classList.add("forge-native");
            """, injectionTime: .atDocumentStart, forMainFrameOnly: true)
        config.userContentController.addUserScript(marker)
        webView = WKWebView(frame: .zero, configuration: config)
        super.init()
        config.userContentController.add(WeakScriptHandler(self), name: "forgeHaptic")

        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsLinkPreview = false
        webView.allowsBackForwardNavigationGestures = false
        webView.scrollView.bounces = false
        webView.scrollView.contentInsetAdjustmentBehavior = .never   // web layer owns safe areas
        webView.isOpaque = true
        webView.backgroundColor = ForgeConfig.background
        webView.scrollView.backgroundColor = ForgeConfig.background
        #if DEBUG
        if #available(iOS 16.4, *) { webView.isInspectable = true }   // Safari → Develop
        #endif

        let nc = NotificationCenter.default
        nc.addObserver(self, selector: #selector(didBackground), name: UIApplication.didEnterBackgroundNotification, object: nil)
        nc.addObserver(self, selector: #selector(didForeground), name: UIApplication.didBecomeActiveNotification, object: nil)
        load()
    }

    func load() {
        phase = .loading
        webView.load(URLRequest(url: ForgeConfig.baseURL, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 20))
    }

    @objc private func didBackground() { backgroundedAt = Date() }

    // Long absences (overnight, a whole shift) reload so the phone never shows a stale
    // morning. Short ones don't: live_sync's 2s poll resumes on its own.
    @objc private func didForeground() {
        defer { backgroundedAt = nil }
        if case .failed = phase { load(); return }
        if let t = backgroundedAt, Date().timeIntervalSince(t) > ForgeConfig.reloadAfterBackground { load() }
    }

    fileprivate func isOurs(_ url: URL) -> Bool {
        let base = ForgeConfig.baseURL
        return url.host == base.host && url.port == base.port && url.scheme == base.scheme
    }
}

// WKUserContentController retains its handlers; a direct reference would leak the shell.
private final class WeakScriptHandler: NSObject, WKScriptMessageHandler {
    weak var target: ForgeShell?
    init(_ target: ForgeShell) { self.target = target }
    func userContentController(_ c: WKUserContentController, didReceive message: WKScriptMessage) {
        switch message.body as? String {
        case "success": UINotificationFeedbackGenerator().notificationOccurred(.success)
        case "error": UINotificationFeedbackGenerator().notificationOccurred(.error)
        default: UIImpactFeedbackGenerator(style: .light).impactOccurred()
        }
    }
}

extension ForgeShell: WKNavigationDelegate {
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { decisionHandler(.cancel); return }
        let scheme = url.scheme?.lowercased() ?? ""
        // Sub-frames and in-page schemes load normally; the policy guards the app itself.
        if action.targetFrame?.isMainFrame == false || ["about", "data", "blob"].contains(scheme) || isOurs(url) {
            decisionHandler(.allow); return
        }
        // tel: (call a seller / prospect), mailto:, and every other host go to the system.
        // A foreign page loaded in place would be a dead end: no URL bar, no back button.
        decisionHandler(.cancel)
        UIApplication.shared.open(url)
    }

    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        if response.isForMainFrame, let http = response.response as? HTTPURLResponse, http.statusCode >= 500 {
            phase = .failed("The box answered HTTP \(http.statusCode). FORGE may be restarting — try again in a minute.")
            decisionHandler(.cancel); return
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { phase = .ready }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        fail(error)
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        fail(error)
    }

    private func fail(_ error: Error) {
        let e = error as NSError
        if e.domain == NSURLErrorDomain && e.code == NSURLErrorCancelled { return }
        if e.domain == "WebKitErrorDomain" && e.code == 102 { return }   // frame load interrupted (we cancelled it)
        phase = .failed(e.localizedDescription)
    }

    // iOS jetsams the web content process under memory pressure; the view goes white and
    // stays white until force-quit. Reload the same place instead.
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        if webView.url != nil { webView.reload() } else { load() }
    }
}

extension ForgeShell: WKUIDelegate {
    // Every approve/handoff/clock action on mobile sits behind window.confirm(). WKWebView
    // answers confirm() with false unless we present it — the gate would silently eat
    // every tap. Each completion handler must run exactly once, even with no presenter.
    private func present(_ alert: UIAlertController) -> Bool {
        guard let root = UIApplication.shared.connectedScenes
            .compactMap({ ($0 as? UIWindowScene)?.keyWindow?.rootViewController }).first else { return false }
        var top = root
        while let next = top.presentedViewController { top = next }
        top.present(alert, animated: true)
        return true
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let a = UIAlertController(title: nil, message: message, preferredStyle: .alert)
        a.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler() })
        if !present(a) { completionHandler() }
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let a = UIAlertController(title: nil, message: message, preferredStyle: .alert)
        a.addAction(UIAlertAction(title: "Cancel", style: .cancel) { _ in completionHandler(false) })
        a.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler(true) })
        if !present(a) { completionHandler(false) }
    }

    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String,
                 defaultText: String?, initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping (String?) -> Void) {
        let a = UIAlertController(title: nil, message: prompt, preferredStyle: .alert)
        a.addTextField { $0.text = defaultText }
        a.addAction(UIAlertAction(title: "Cancel", style: .cancel) { _ in completionHandler(nil) })
        a.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler(a.textFields?.first?.text) })
        if !present(a) { completionHandler(nil) }
    }

    // window.open / target=_blank never reach the navigation delegate; without this the
    // tap does nothing. Ours → load in place; anything else → the system.
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url {
            if isOurs(url) { webView.load(action.request) } else { UIApplication.shared.open(url) }
        }
        return nil
    }
}

struct WebContainer: UIViewRepresentable {
    let webView: WKWebView
    func makeUIView(context: Context) -> WKWebView { webView }
    func updateUIView(_ uiView: WKWebView, context: Context) {}
}

struct ContentView: View {
    @StateObject private var shell = ForgeShell()

    var body: some View {
        ZStack {
            Color(ForgeConfig.background).ignoresSafeArea()
            WebContainer(webView: shell.webView)
                .ignoresSafeArea()
                .opacity(shell.phase == .ready ? 1 : 0)
            switch shell.phase {
            case .loading:
                VStack(spacing: 14) {
                    Text("FORGE").font(.system(size: 30, weight: .heavy)).foregroundColor(Color(red: 0.094, green: 0.145, blue: 0.255))
                    ProgressView()
                }
            case .failed(let why):
                VStack(spacing: 14) {
                    Image(systemName: "wifi.exclamationmark").font(.system(size: 40)).foregroundColor(.orange)
                    Text("Can't reach FORGE").font(.title3.weight(.bold))
                    Text("FORGE runs on your box over Tailscale. Make sure Tailscale is connected on this phone, then retry.")
                        .font(.subheadline).foregroundColor(.secondary).multilineTextAlignment(.center)
                    Text(why).font(.footnote).foregroundColor(.secondary).multilineTextAlignment(.center)
                    Button(action: { shell.load() }) {
                        Text("Retry").font(.headline).frame(maxWidth: 220, minHeight: 48)
                    }
                    .buttonStyle(.borderedProminent)
                }
                .padding(32)
            case .ready:
                EmptyView()
            }
        }
    }
}
