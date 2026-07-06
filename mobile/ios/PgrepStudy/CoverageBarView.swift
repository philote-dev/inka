// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// The coverage bar for the mobile Progress surface: one segment per blueprint
// category, each sized to its blueprint weight, filled when the category is
// covered (at least one reviewed card) and faint when not, with a marker at the
// Readiness coverage gate. A native port of the desktop CoverageBar
// (ts/lib/components/CoverageBar.svelte), drawn with a plain SwiftUI Canvas so it
// always renders. Coverage is not one of the three reserved score hues, so it is
// monochrome by design (covered = text tone, uncovered = border tone).

import SwiftUI

/// One category's slice of the coverage bar.
struct CoverageSegment: Identifiable, Equatable {
    let id: String
    let weight: Double
    let covered: Bool
}

struct CoverageBarView: View {
    let segments: [CoverageSegment]
    /// The Readiness gate as a fraction (0..1); a caution-tone marker sits here.
    let gate: Double

    var body: some View {
        Canvas { context, size in
            let total = segments.reduce(0.0) { $0 + $1.weight }
            guard total > 0 else { return }

            var x = 0.0
            for segment in segments {
                let width = size.width * (segment.weight / total)
                // A hairline gap between segments keeps the categories legible.
                let rect = CGRect(x: x, y: 0, width: max(0, width - 1.5), height: size.height)
                let color = segment.covered ? Theme.text : Theme.border
                context.fill(
                    Path(roundedRect: rect, cornerRadius: 2, style: .continuous),
                    with: .color(color)
                )
                x += width
            }

            // Gate marker: a caution-tone tick spanning the bar's full height.
            let gateX = size.width * min(max(gate, 0.0), 1.0)
            var tick = Path()
            tick.move(to: CGPoint(x: gateX, y: -3))
            tick.addLine(to: CGPoint(x: gateX, y: size.height + 3))
            context.stroke(tick, with: .color(Theme.caution), lineWidth: 2)
        }
        .frame(height: 12)
        .accessibilityElement()
        .accessibilityLabel("Coverage by category, with the Readiness gate marked")
    }
}
