// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Hosts the real 3D knowledge manifold on the native Home. This is the same
// WebGL/Three.js renderer the desktop web Home draws (ts/lib/pgrep/manifold3d),
// bundled self-contained (tools/build-manifold-webview.sh) and loaded from the
// app bundle into a WKWebView, so the phone matches desktop instead of a 2D
// fallback. The surface is built natively from the synced Memory (ManifoldSurface
// mirrors the desktop read model), and handed to the page over a JS bridge; the
// page reports "ready", we push the surface + theme, and re-push whenever the
// scores or the light/dark theme change. WebGL runs entirely on-device; the page
// makes no network calls.

import SwiftUI
import WebKit

/// A drag-to-orbit WebGL manifold, sized to its SwiftUI frame.
struct ManifoldWebView: View {
    let surface: ManifoldSurface
    /// The active color scheme, threaded so the renderer picks the matching
    /// reserved hues (amber/blue/lilac) and line weights, exactly like desktop's
    /// night-mode switch.
    var colorScheme: ColorScheme

    var body: some View {
        ManifoldWebViewRepresentable(surface: surface, theme: colorScheme == .dark ? "dark" : "light")
            .background(Theme.elevated)
            .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous)
                    .stroke(Theme.border, lineWidth: 1)
            )
            .accessibilityLabel("Knowledge manifold, your topics as a 3D map")
    }
}

// MARK: - WKWebView bridge

private struct ManifoldWebViewRepresentable: UIViewRepresentable {
    let surface: ManifoldSurface
    let theme: String

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.userContentController.add(context.coordinator, name: "manifold")
        let webView = WKWebView(frame: .zero, configuration: config)
        webView.isOpaque = false
        webView.backgroundColor = .clear
        webView.scrollView.backgroundColor = .clear
        webView.scrollView.isScrollEnabled = false
        webView.scrollView.bounces = false
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        context.coordinator.webView = webView

        if let page = Self.pageURL() {
            webView.loadFileURL(page, allowingReadAccessTo: page.deletingLastPathComponent())
        }
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        context.coordinator.apply(surface: surface, theme: theme)
    }

    static func dismantleUIView(_ webView: WKWebView, coordinator: Coordinator) {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "manifold")
    }

    /// The bundled host page (manifold.html sits beside manifold.bundle.js in the
    /// app bundle's resources).
    private static func pageURL() -> URL? {
        Bundle.main.url(forResource: "manifold", withExtension: "html")
    }

    final class Coordinator: NSObject, WKScriptMessageHandler {
        weak var webView: WKWebView?
        private var ready = false
        private var lastSent: String?
        private var pending: String?

        /// Push a new surface/theme, or stash it until the page reports ready.
        func apply(surface: ManifoldSurface, theme: String) {
            let payload = "{\"surface\":\(surface.jsonString()),"
                + "\"theme\":\"\(theme)\",\"grid\":72,\"heightScale\":1.2,\"interactive\":true}"
            guard payload != lastSent else { return }
            pending = payload
            flush()
        }

        private func flush() {
            guard ready, let payload = pending, let webView else { return }
            lastSent = payload
            pending = nil
            webView.evaluateJavaScript(
                "window.pgrepManifold && window.pgrepManifold.render(\(payload));",
                completionHandler: nil
            )
        }

        func userContentController(
            _ controller: WKUserContentController,
            didReceive message: WKScriptMessage
        ) {
            guard message.name == "manifold",
                  let body = message.body as? [String: Any],
                  let type = body["type"] as? String
            else { return }
            if type == "ready" {
                ready = true
                flush()
            }
        }
    }
}
