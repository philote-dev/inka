// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Proof that the math renderer typesets offline: the generated document must
// reference the bundled MathJax (no CDN, no network), keep the desktop's tex
// config and self-sizing, and the committed tex-svg-full asset must exist so
// xcodegen bundles it. WKWebView rendering itself is not unit-testable here, so
// we assert the document contract and the resource on disk.

import Foundation
import XCTest

final class MathTextTests: XCTestCase {
    private func sampleDocument(
        body: String = "Mass \\(m\\) and energy \\[E = mc^2\\].",
        fontSize: CGFloat = 17,
        weight: MathHTML.Weight = .regular,
        centered: Bool = false
    ) -> String {
        MathHTML.document(body: body, fontSize: fontSize, weight: weight, centered: centered)
    }

    /// The document loads MathJax locally and carries no remote references, so
    /// typesetting works with no network (the whole point of this task).
    func testDocumentReferencesBundledMathJaxNotCDN() {
        let doc = sampleDocument()

        XCTAssertTrue(
            doc.contains("src=\"\(MathHTML.scriptName)\""),
            "the document should load the bundled MathJax by relative src"
        )
        XCTAssertEqual(MathHTML.scriptName, "tex-svg-full.js", "we ship the self-contained SVG build")

        for remote in ["cdn.jsdelivr", "mathjax@3", "http://", "https://"] {
            XCTAssertFalse(
                doc.contains(remote),
                "the document must not reference \(remote) (offline only)"
            )
        }
    }

    /// The MathJax config and self-sizing behavior match the previous CDN build:
    /// same delimiters, skip list, and height reporting.
    func testDocumentPreservesMathJaxConfigAndSizing() {
        let doc = sampleDocument()

        XCTAssertTrue(doc.contains("inlineMath"), "keeps the inline delimiters")
        XCTAssertTrue(doc.contains("displayMath"), "keeps the display delimiters")
        XCTAssertTrue(doc.contains("skipHtmlTags"), "keeps the skip list")
        XCTAssertTrue(doc.contains("reportHeight"), "keeps the height reporter")
        XCTAssertTrue(doc.contains("ResizeObserver"), "keeps the resize observer")
        XCTAssertTrue(doc.contains("messageHandlers.height"), "keeps the height bridge")
        XCTAssertTrue(doc.contains("mjx-container"), "keeps the MathJax container styling")
    }

    /// Font size, weight, and alignment still flow into the document CSS, so call
    /// sites (card front/back, exam, ladder) look unchanged.
    func testDocumentAppliesFontAndAlignment() {
        let defaultDoc = sampleDocument(fontSize: 24, weight: .regular, centered: false)
        XCTAssertTrue(defaultDoc.contains("font-size: 24px;"), "font size flows through")
        XCTAssertTrue(defaultDoc.contains("font-weight: 400;"), "regular weight flows through")
        XCTAssertTrue(defaultDoc.contains("text-align: left;"), "left alignment by default")

        let emphasized = sampleDocument(weight: .semibold, centered: true)
        XCTAssertTrue(emphasized.contains("font-weight: 600;"), "semibold weight flows through")
        XCTAssertTrue(emphasized.contains("text-align: center;"), "centered alignment flows through")
    }

    /// The committed MathJax asset exists in the source tree, so xcodegen globs it
    /// into the app's Resources. Resolved from this test file's path because the
    /// standalone (host-less) test bundle does not carry the app's resources.
    func testBundledMathJaxAssetExists() throws {
        let assetURL = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // PgrepStudyTests
            .deletingLastPathComponent() // mobile/ios
            .appendingPathComponent("PgrepStudy/Resources/MathJax/\(MathHTML.scriptName)")

        XCTAssertTrue(
            FileManager.default.fileExists(atPath: assetURL.path),
            "bundled MathJax should exist at \(assetURL.path)"
        )
        let size = try FileManager.default.attributesOfItem(atPath: assetURL.path)[.size] as? Int
        XCTAssertGreaterThan(
            size ?? 0, 1_000_000,
            "tex-svg-full should be the full self-contained build (~2MB)"
        )
    }
}
