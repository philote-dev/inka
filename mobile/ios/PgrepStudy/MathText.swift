// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Math-aware rendering for card and problem text. Anki/pgrep fields carry light
// HTML plus LaTeX math in \(..\) / \[..\] / $..$ delimiters (the desktop typesets
// these with MathJax, ts/lib/pgrep/math). HTMLText.plain strips tags but leaves
// math as raw delimiters, so this view renders the real thing: a self-sizing,
// non-interactive WKWebView that loads MathJax and typesets the field.
//
// Offline/degradation: MathJax loads from a CDN; if it cannot load (offline),
// the field still renders as readable HTML text (the delimiters remain visible),
// and the view still sizes itself, so nothing breaks. Bundling MathJax for fully
// offline typesetting is a deliberate follow-up (see TODO below) rather than a
// heavy addition here.
//
// The web view is non-interactive (allowsHitTesting false, scrolling off) so it
// composes cleanly inside SwiftUI Buttons (choice rows) and ScrollViews without
// stealing gestures.
//
// TODO(offline-math): bundle MathJax (es5/tex-mml-chtml) into the app resources
// and load it via a file:// baseURL so typesetting works with no network.

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

    /// The full HTML document: theme-matched CSS, MathJax config + CDN load with
    /// an onerror fallback, and a ResizeObserver that reports the content height.
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
        <script async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js" onerror="reportHeight()"></script>
        </head>
        <body>\(body)</body>
        </html>
        """
    }
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
        webView.loadHTMLString(
            MathHTML.document(body: html, fontSize: fontSize, weight: weight, centered: centered),
            baseURL: nil
        )
    }

    static func dismantleUIView(_ webView: WKWebView, coordinator: Coordinator) {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "height")
    }

    final class Coordinator: NSObject, WKScriptMessageHandler {
        @Binding var height: CGFloat
        var loadedSignature: String?

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
