// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Math-aware rendering for card and problem text. Anki/pgrep fields carry light
// HTML plus LaTeX math in \(..\) / \[..\] / $..$ delimiters (the desktop typesets
// these with MathJax, ts/lib/pgrep/math). HTMLText.plain strips tags but leaves
// math as raw delimiters, so this view renders the real thing: a self-sizing,
// non-interactive WKWebView that loads MathJax and typesets the field.
//
// Offline typesetting: MathJax ships inside the app (Resources/MathJax, the same
// tex-svg-full build the ts toolchain imports) and is served, together with the
// generated document, over a private URL scheme so nothing touches the network.
// SVG output means the glyphs live in the script itself, so there are no CHTML
// web-font downloads either. If MathJax somehow fails to load, the field still
// renders as readable HTML text (the delimiters remain visible) and the view
// still sizes itself, so nothing breaks.
//
// We serve through a WKURLSchemeHandler rather than loadHTMLString because a
// string load gets an opaque origin and cannot read bundled file resources, and
// loadFileURL needs a real file for a document that is generated per field. The
// scheme handler hands back both the document and the bundled script from memory.
//
// The web view is non-interactive (allowsHitTesting false, scrolling off) so it
// composes cleanly inside SwiftUI Buttons (choice rows) and ScrollViews without
// stealing gestures.

import SwiftUI
import WebKit

/// Renders a field's HTML with LaTeX math, sizing itself to the typeset content.
struct MathText: View {
    let html: String
    var fontSize: CGFloat = 17
    var weight: MathHTML.Weight = .regular
    var centered: Bool = false

    // Grows to the typeset content height; the initial estimate keeps layout
    // stable before the first height message arrives.
    @State private var height: CGFloat = 22

    var body: some View {
        MathWebView(
            html: html,
            fontSize: fontSize,
            weight: weight,
            centered: centered,
            height: $height
        )
        .frame(height: height)
        .allowsHitTesting(false)
    }
}

// MARK: - HTML document

enum MathHTML {
    enum Weight {
        case regular
        case semibold

        var css: String { self == .semibold ? "600" : "400" }
    }

    /// The private scheme the document and MathJax are served over. It must not
    /// collide with a scheme WebKit already handles (http, file, ...).
    static let scheme = "pgrepmath"
    /// The document's own URL path under that scheme.
    static let indexPath = "index.html"
    /// The bundled MathJax script, referenced by the document with a relative src
    /// so it resolves against the scheme base and loads from the app bundle.
    static let scriptName = "tex-svg-full.js"

    /// The full HTML document: theme-matched CSS, MathJax config, the local
    /// MathJax load with an onerror fallback, and a ResizeObserver that reports
    /// the content height.
    static func document(body: String, fontSize: CGFloat, weight: Weight, centered: Bool) -> String {
        let align = centered ? "center" : "left"
        return """
        <!doctype html>
        <html>
        <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
        <style>
          :root { color-scheme: light dark; }
          html, body { margin: 0; padding: 0; background: transparent; }
          body {
            font-family: -apple-system, system-ui, "Helvetica Neue", sans-serif;
            font-size: \(Int(fontSize))px;
            font-weight: \(weight.css);
            line-height: 1.5;
            color: #262624;
            text-align: \(align);
            -webkit-text-size-adjust: 100%;
            overflow-wrap: break-word;
            word-break: break-word;
          }
          @media (prefers-color-scheme: dark) { body { color: #ECEAE3; } }
          p { margin: 0 0 0.5em; }
          p:last-child { margin-bottom: 0; }
          ol, ul { margin: 0 0 0.4em; padding-left: 1.4em; }
          li { margin: 0 0 0.25em; }
          img { max-width: 100%; height: auto; }
          .answer { font-weight: 600; }
          mjx-container { overflow-x: auto; overflow-y: hidden; max-width: 100%; }
        </style>
        <script>
          window.MathJax = {
            tex: {
              inlineMath: [['\\\\(', '\\\\)'], ['$', '$']],
              displayMath: [['\\\\[', '\\\\]'], ['$$', '$$']]
            },
            options: { skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre'] },
            startup: {
              typeset: true,
              ready: function () {
                MathJax.startup.defaultReady();
                MathJax.startup.promise.then(reportHeight);
              }
            }
          };
          function reportHeight() {
            var h = Math.ceil(document.body.getBoundingClientRect().height);
            try { window.webkit.messageHandlers.height.postMessage(h); } catch (e) {}
          }
          window.addEventListener('load', function () { setTimeout(reportHeight, 0); });
          if (window.ResizeObserver) {
            new ResizeObserver(function () { reportHeight(); }).observe(document.documentElement);
          }
        </script>
        <script async src="\(scriptName)" onerror="reportHeight()"></script>
        </head>
        <body>\(body)</body>
        </html>
        """
    }
}

// MARK: - Offline resource serving

/// Serves the generated document and the bundled MathJax script over the private
/// `pgrepmath` scheme, so the web view typesets with no network access. Both
/// payloads are answered synchronously from memory, so a task is never left in
/// flight for `stop(_:)` to race.
private final class MathSchemeHandler: NSObject, WKURLSchemeHandler {
    /// The document to answer the index request with; refreshed per field.
    var document = ""

    /// The bundled MathJax script, read once and shared by every handler so many
    /// on-screen fields do not each hold a copy of the ~2MB build.
    private static let scriptData: Data? = {
        guard let url = Bundle.main.url(forResource: "tex-svg-full", withExtension: "js") else {
            return nil
        }
        return try? Data(contentsOf: url)
    }()

    func webView(_ webView: WKWebView, start task: WKURLSchemeTask) {
        guard let url = task.request.url else {
            task.didFailWithError(URLError(.badURL))
            return
        }
        let name = url.lastPathComponent
        let payload: (data: Data, mime: String)?
        switch name {
        case MathHTML.indexPath:
            payload = (Data(document.utf8), "text/html")
        case MathHTML.scriptName:
            payload = Self.scriptData.map { ($0, "text/javascript") }
        default:
            payload = nil
        }
        guard let payload else {
            task.didFailWithError(URLError(.fileDoesNotExist))
            return
        }
        let response = URLResponse(
            url: url,
            mimeType: payload.mime,
            expectedContentLength: payload.data.count,
            textEncodingName: "utf-8"
        )
        task.didReceive(response)
        task.didReceive(payload.data)
        task.didFinish()
    }

    func webView(_ webView: WKWebView, stop task: WKURLSchemeTask) {}
}

// MARK: - WKWebView bridge

private struct MathWebView: UIViewRepresentable {
    let html: String
    let fontSize: CGFloat
    let weight: MathHTML.Weight
    let centered: Bool
    @Binding var height: CGFloat

    func makeCoordinator() -> Coordinator { Coordinator(height: $height) }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.userContentController.add(context.coordinator, name: "height")
        config.setURLSchemeHandler(context.coordinator.schemeHandler, forURLScheme: MathHTML.scheme)
        let webView = WKWebView(frame: .zero, configuration: config)
        webView.scrollView.isScrollEnabled = false
        webView.scrollView.bounces = false
        webView.isOpaque = false
        webView.backgroundColor = .clear
        webView.scrollView.backgroundColor = .clear
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        let signature = "\(fontSize)|\(weight.css)|\(centered)|\(html)"
        guard context.coordinator.loadedSignature != signature else { return }
        context.coordinator.loadedSignature = signature
        context.coordinator.schemeHandler.document = MathHTML.document(
            body: html,
            fontSize: fontSize,
            weight: weight,
            centered: centered
        )
        guard let index = URL(string: "\(MathHTML.scheme)://mathjax/\(MathHTML.indexPath)") else { return }
        webView.load(URLRequest(url: index))
    }

    static func dismantleUIView(_ webView: WKWebView, coordinator: Coordinator) {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "height")
    }

    final class Coordinator: NSObject, WKScriptMessageHandler {
        @Binding var height: CGFloat
        var loadedSignature: String?
        let schemeHandler = MathSchemeHandler()

        init(height: Binding<CGFloat>) { _height = height }

        func userContentController(
            _ controller: WKUserContentController,
            didReceive message: WKScriptMessage
        ) {
            guard message.name == "height",
                  let value = (message.body as? NSNumber)?.doubleValue
            else { return }
            let newHeight = CGFloat(max(1, value))
            // Defer out of the current layout pass; only apply real changes so a
            // ResizeObserver settling does not churn SwiftUI layout.
            DispatchQueue.main.async { [weak self] in
                guard let self, abs(self.height - newHeight) > 0.5 else { return }
                self.height = newHeight
            }
        }
    }
}
