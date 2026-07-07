// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// The calibration reliability diagram: predicted probability against observed
// outcome rate, with the perfect-calibration diagonal and a Brier score. A native
// port of ts/lib/components/ReliabilityDiagram.svelte, drawn with a SwiftUI Canvas
// (no WebView), the same approach CoverageBarView uses so it always renders.
//
// With no graded points it draws the empty frame and abstains rather than
// inventing a curve. The curve takes the layer's reserved data hue (Memory amber
// or Performance blue); the axes and diagonal stay monochrome, since only the
// data carries meaning (ux-foundation.md).

import SwiftUI

struct ReliabilityDiagramView: View {
    let points: [ReliabilityPoint]
    var brier: Double? = nil
    /// A short honest read shown next to the Brier (e.g. "Not enough graded
    /// evidence yet"). The Svelte's `read`.
    var read: String = ""
    /// The reserved data hue for the curve. Calibration covers the Memory and
    /// Performance layers; defaults to Performance.
    var tone: ScoreKind = .performance
    var size: CGFloat = 220

    private var geo: ReliabilityGeometry { ReliabilityGeometry(size: Double(size)) }

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Space.s - 2) {
            chart
                .frame(width: size, height: size)
                .accessibilityElement()
                .accessibilityLabel(Text(accessibilityLabel))
            foot
                .padding(.leading, CGFloat(geo.pad))
        }
        .frame(width: size, alignment: .leading)
    }

    // MARK: Chart

    private var chart: some View {
        Canvas { context, _ in
            let curve = tone.fill

            // Axes: the bottom and left edges, in the border tone.
            var axes = Path()
            axes.move(to: point(geo.x(0), geo.y(0)))
            axes.addLine(to: point(geo.x(1), geo.y(0)))
            axes.move(to: point(geo.x(0), geo.y(0)))
            axes.addLine(to: point(geo.x(0), geo.y(1)))
            context.stroke(axes, with: .color(Theme.border), lineWidth: 1)

            // Perfect-calibration diagonal, dashed and faint.
            var diagonal = Path()
            diagonal.move(to: point(geo.x(0), geo.y(0)))
            diagonal.addLine(to: point(geo.x(1), geo.y(1)))
            context.stroke(
                diagonal,
                with: .color(Theme.muted.opacity(0.6)),
                style: StrokeStyle(lineWidth: 1, dash: [3, 4])
            )

            // The reliability curve, only when there is more than one point.
            if points.count > 1 {
                var line = Path()
                for (index, p) in points.enumerated() {
                    let c = point(geo.x(p.predicted), geo.y(p.observed))
                    if index == 0 { line.move(to: c) } else { line.addLine(to: c) }
                }
                context.stroke(
                    line,
                    with: .color(curve),
                    style: StrokeStyle(lineWidth: 1.5, lineCap: .round, lineJoin: .round)
                )
            }

            // The points.
            let radius = 2.5
            for p in points {
                let c = point(geo.x(p.predicted), geo.y(p.observed))
                let dot = Path(
                    ellipseIn: CGRect(
                        x: c.x - radius, y: c.y - radius,
                        width: radius * 2, height: radius * 2
                    )
                )
                context.fill(dot, with: .color(curve))
            }
        }
        .overlay {
            // Axis labels as real Text, so they stay legible and accessible.
            Text("predicted")
                .font(.system(size: 10))
                .foregroundStyle(Theme.muted)
                .position(x: CGFloat(geo.x(0.5)), y: size - 8)
            Text("observed")
                .font(.system(size: 10))
                .foregroundStyle(Theme.muted)
                .fixedSize()
                .rotationEffect(.degrees(-90))
                .position(x: 10, y: CGFloat(geo.y(0.5)))
        }
    }

    // MARK: Foot

    private var foot: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            if let brierText = ReliabilityDiagram.formatBrier(brier) {
                Text("Brier \(brierText)")
                    .font(Theme.Typography.mono(12))
                    .foregroundStyle(Theme.text)
            }
            if !read.isEmpty {
                Text(read)
                    .font(Theme.Typography.small)
                    .foregroundStyle(Theme.muted)
            }
        }
    }

    private func point(_ x: Double, _ y: Double) -> CGPoint {
        CGPoint(x: x, y: y)
    }

    private var accessibilityLabel: String {
        var parts = ["\(tone.rawValue) calibration reliability diagram"]
        if let brierText = ReliabilityDiagram.formatBrier(brier) {
            parts.append("Brier \(brierText)")
        }
        if !read.isEmpty {
            parts.append(read)
        }
        parts.append("predicted probability against observed outcome, with the perfect-calibration diagonal")
        return parts.joined(separator: ". ")
    }
}

// MARK: - Preview

#if DEBUG
// A well-calibrated Performance read, an underconfident Memory read, and the
// empty frame when nothing is graded yet. The values mirror the desktop gallery
// (which in turn mirrors anki.pgrep.calibration_evidence).
private let reliabilityPreviewPerformance: [ReliabilityPoint] = [
    .init(predicted: 0.1, observed: 0.09),
    .init(predicted: 0.3, observed: 0.31),
    .init(predicted: 0.5, observed: 0.48),
    .init(predicted: 0.7, observed: 0.69),
    .init(predicted: 0.9, observed: 0.90),
]

private let reliabilityPreviewMemory: [ReliabilityPoint] = [
    .init(predicted: 0.1, observed: 0.20),
    .init(predicted: 0.3, observed: 0.44),
    .init(predicted: 0.5, observed: 0.63),
    .init(predicted: 0.7, observed: 0.82),
    .init(predicted: 0.9, observed: 0.95),
]

private struct ReliabilityDiagramPreviewGallery: View {
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Space.xl) {
                cell("Performance, well calibrated") {
                    ReliabilityDiagramView(
                        points: reliabilityPreviewPerformance,
                        brier: 0.175,
                        read: "Well calibrated",
                        tone: .performance
                    )
                }
                cell("Memory, underconfident") {
                    ReliabilityDiagramView(
                        points: reliabilityPreviewMemory,
                        brier: 0.234,
                        read: "Slightly overconfident",
                        tone: .memory
                    )
                }
                cell("No evidence yet, honest empty frame") {
                    ReliabilityDiagramView(
                        points: [],
                        brier: nil,
                        read: "Not enough graded evidence yet",
                        tone: .performance
                    )
                }
            }
            .padding(Theme.Space.l)
        }
        .background(Theme.canvas)
    }

    private func cell(_ title: String, @ViewBuilder _ content: () -> some View) -> some View {
        VStack(alignment: .leading, spacing: Theme.Space.s) {
            Text(title)
                .font(Theme.Typography.caption)
                .foregroundStyle(Theme.muted)
            content()
        }
    }
}

#Preview("Reliability light") {
    ReliabilityDiagramPreviewGallery().preferredColorScheme(.light)
}

#Preview("Reliability dark") {
    ReliabilityDiagramPreviewGallery().preferredColorScheme(.dark)
}
#endif
