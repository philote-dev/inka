// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Pure, testable core for the calibration reliability diagram, ported from
// ts/lib/components/ReliabilityDiagram.svelte. It holds the point model, the
// coordinate transform, and the Brier formatting; ReliabilityDiagramView.swift
// draws them with a SwiftUI Canvas. The input shape mirrors the output of
// anki.pgrep.calibration_evidence: reliability points ({predicted, observed}),
// a Brier score, a sample n, and a short honest note.

import Foundation

/// One reliability point: the model's predicted probability against the observed
/// outcome rate for that bin. Mirrors the `{ p, o }` pair produced by
/// anki.pgrep.calibration_evidence (`predicted`/`observed` spelled out here).
struct ReliabilityPoint: Equatable {
    /// Predicted probability, 0..1 (the x axis).
    let predicted: Double
    /// Observed outcome rate, 0..1 (the y axis).
    let observed: Double

    init(predicted: Double, observed: Double) {
        self.predicted = predicted
        self.observed = observed
    }
}

/// The coordinate transform for the square chart: a `size` box with `pad`
/// reserved at the left and bottom for the axes and a small `tail` at the top and
/// right so the (1, 1) corner is not clipped. Ported from the px()/py() helpers
/// in ReliabilityDiagram.svelte (pad 28, tail 10). Pure Double math, so the
/// mapping is unit-tested without building a view.
struct ReliabilityGeometry: Equatable {
    let size: Double
    var pad: Double = 28
    var tail: Double = 10

    /// The drawable span between the axis origin and the far edge.
    var span: Double { size - pad - tail }

    /// Map a 0..1 value to an x coordinate (origin at the left axis).
    func x(_ value: Double) -> Double { pad + value * span }

    /// Map a 0..1 value to a y coordinate. Screen y grows downward, so a higher
    /// observed value sits higher up (a smaller y).
    func y(_ value: Double) -> Double { size - pad - value * span }
}

/// Namespaced logic for the reliability diagram (no SwiftUI, so it is testable).
enum ReliabilityDiagram {
    /// Format a Brier score for display: rounded to three decimals with trailing
    /// zeros trimmed, matching the desktop (which rounds with `round3` before
    /// handing the number to ReliabilityDiagram). Returns nil when there is no
    /// score, so the diagram omits the figure rather than showing a placeholder.
    static func formatBrier(_ brier: Double?) -> String? {
        guard let brier else { return nil }
        let rounded = (brier * 1000).rounded() / 1000
        if rounded == rounded.rounded() {
            return String(Int(rounded))
        }
        var text = String(format: "%.3f", rounded)
        while text.hasSuffix("0") { text.removeLast() }
        if text.hasSuffix(".") { text.removeLast() }
        return text
    }
}
