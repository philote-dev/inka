// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Progress: the coverage ledger, the three score cards, and the calibration
// evidence for the mobile companion, mirroring the desktop Progress surface
// (ts/routes/pgrep/progress/+page.svelte, the Coverage + Scores + Calibration
// tabs). Coverage shows how much of the blueprint has a reviewed card (a
// segmented bar per category, the overall fraction against the Readiness gate,
// and a per-category list reusing each topic's Memory point). The three cards
// then read Memory, Performance, and Readiness with their 80% ranges, each
// abstaining honestly on thin data. Calibration reads the embedded offline
// evidence (calibration_evidence.py), a reliability diagram plus Brier for
// Memory and Performance, never the private content/ tree. All computed natively
// over the shared engine, the same snapshot Home reads.

import SwiftUI

/// Human-readable category labels, mirroring the desktop CATEGORY_LABELS map.
enum CategoryLabels {
    static let byCategory: [String: String] = [
        "mechanics": "Mechanics",
        "electromagnetism": "Electromagnetism",
        "quantum": "Quantum",
        "thermodynamics": "Thermodynamics",
        "atomic": "Atomic physics",
        "optics_waves": "Optics and waves",
        "special_relativity": "Special relativity",
        "lab": "Lab methods",
        "specialized": "Specialized",
    ]

    static func label(_ slug: String) -> String {
        byCategory[slug] ?? slug.replacingOccurrences(of: "_", with: " ")
    }
}

/// The Progress facets, one segmented control, mirroring the desktop tabs so each
/// facet of the evidence lives in its own home rather than a long scroll.
private enum ProgressTab: String, CaseIterable, Identifiable {
    case coverage
    case scores
    case calibration

    var id: String { rawValue }

    var title: String {
        switch self {
        case .coverage: return "Coverage"
        case .scores: return "Scores"
        case .calibration: return "Calibration"
        }
    }
}

@MainActor
final class ProgressModel: ObservableObject {
    enum LoadState: Equatable {
        case loading
        case loaded(Scoreboard)
        case failed(String)
    }

    @Published private(set) var state: LoadState = .loading

    func load(engine: Engine) async {
        state = .loading
        do {
            state = .loaded(try await engine.computeScoreboard())
        } catch {
            state = .failed(String(describing: error))
        }
    }
}

struct ProgressScreen: View {
    @EnvironmentObject private var app: AppModel
    @StateObject private var model = ProgressModel()
    @Binding var selectedTab: RootTab
    @State private var tab: ProgressTab = .coverage

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Space.l) {
                content
            }
            .padding(Theme.Space.l)
        }
        .background(Theme.canvas.ignoresSafeArea())
        .task(id: app.dataVersion) { await model.load(engine: app.engine) }
    }

    @ViewBuilder
    private var content: some View {
        switch model.state {
        case .loading:
            ProgressView("Reading your coverage…")
                .frame(maxWidth: .infinity, minHeight: 200)
        case let .loaded(board):
            if app.diagnosticDone == false {
                DiagnosticCTA { app.isPresentingDiagnostic = true }
            }
            Picker("Section", selection: $tab) {
                ForEach(ProgressTab.allCases) { Text($0.title).tag($0) }
            }
            .pickerStyle(.segmented)
            tabContent(board)
        case let .failed(message):
            VStack(spacing: Theme.Space.m) {
                Image(systemName: "exclamationmark.triangle")
                    .font(.system(size: 32))
                    .foregroundStyle(Theme.error)
                Text("Could not load progress")
                    .font(Theme.Typography.title)
                    .foregroundStyle(Theme.text)
                Text(message)
                    .font(Theme.Typography.caption)
                    .foregroundStyle(Theme.muted)
                    .multilineTextAlignment(.center)
            }
            .frame(maxWidth: .infinity, minHeight: 200)
        }
    }

    /// Route the selected facet to its panel. Coverage and Scores are the
    /// existing native reads; Calibration renders the embedded offline evidence.
    @ViewBuilder
    private func tabContent(_ board: Scoreboard) -> some View {
        switch tab {
        case .coverage:
            coveragePanel(board.coverage)
        case .scores:
            scoresSection(board)
        case .calibration:
            calibrationSection()
        }
    }

    // MARK: Coverage

    private func coveragePanel(_ coverage: CoverageResult) -> some View {
        let coveredCount = coverage.byTopic.filter(\.covered).count
        let anyCards = coverage.byTopic.contains { $0.nCards > 0 }
        let segments = coverage.byTopic.map {
            CoverageSegment(id: $0.category, weight: $0.blueprint, covered: $0.covered)
        }
        return VStack(alignment: .leading, spacing: Theme.Space.m) {
            HStack(alignment: .firstTextBaseline) {
                Text("Coverage")
                    .font(Theme.Typography.emphasis)
                    .foregroundStyle(Theme.text)
                Spacer()
                Text("\(coveredCount) of \(coverage.byTopic.count) started")
                    .font(Theme.Typography.caption)
                    .foregroundStyle(Theme.muted)
            }

            HStack(alignment: .center, spacing: Theme.Space.l) {
                VStack(alignment: .leading, spacing: Theme.Space.xs) {
                    Text("\(Int((coverage.overallPct * 100).rounded()))%")
                        .font(Theme.Typography.score)
                        .foregroundStyle(Theme.text)
                    Text("of the exam covered")
                        .font(Theme.Typography.caption)
                        .foregroundStyle(Theme.muted)
                }
                VStack(alignment: .trailing, spacing: Theme.Space.s) {
                    Text("Readiness needs \(Int((coverage.gate * 100).rounded()))%")
                        .font(Theme.Typography.mono(12))
                        .foregroundStyle(Theme.muted)
                    CoverageBarView(segments: segments, gate: coverage.gate)
                }
                .frame(maxWidth: .infinity)
            }

            Text("Reviewed coverage. Readiness gates separately on questions attempted, not cards reviewed.")
                .font(Theme.Typography.caption)
                .foregroundStyle(Theme.muted)

            VStack(spacing: Theme.Space.s) {
                ForEach(coverage.byTopic, id: \.category) { topic in
                    coverageRow(topic)
                }
            }

            if !anyCards {
                Text("Study cards to start covering the blueprint.")
                    .font(Theme.Typography.caption)
                    .foregroundStyle(Theme.muted)
                Button("Go to Study") { selectedTab = .study }
                    .font(Theme.Typography.body)
                    .foregroundStyle(Theme.text)
            }
        }
        .padding(Theme.Space.l)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.surface)
        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous)
                .stroke(Theme.border, lineWidth: 1)
        )
    }

    private func coverageRow(_ topic: CoverageTopic) -> some View {
        VStack(alignment: .leading, spacing: Theme.Space.xs) {
            HStack {
                Text(CategoryLabels.label(topic.category))
                    .font(Theme.Typography.body)
                    .foregroundStyle(Theme.text)
                Spacer()
                Text(topic.covered ? "Covered" : "Not covered")
                    .font(Theme.Typography.caption)
                    .foregroundStyle(topic.covered ? Theme.text : Theme.muted)
            }
            HStack(spacing: Theme.Space.m) {
                Text("Blueprint \(Int((topic.blueprint * 100).rounded()))%")
                Text("\(topic.nCards) \(topic.nCards == 1 ? "card" : "cards")")
                if let point = topic.memoryPoint {
                    Text("Memory \(Int((point * 100).rounded()))%")
                        .foregroundStyle(Theme.memoryText)
                }
            }
            .font(Theme.Typography.caption)
            .foregroundStyle(Theme.muted)
        }
        .padding(Theme.Space.m)
        .frame(maxWidth: .infinity, alignment: .leading)
        .overlay(
            RoundedRectangle(cornerRadius: Theme.Radius.row, style: .continuous)
                .stroke(Theme.border, lineWidth: 1)
        )
        .opacity(topic.covered ? 1.0 : 0.68)
    }

    // MARK: Scores

    private func scoresSection(_ board: Scoreboard) -> some View {
        VStack(alignment: .leading, spacing: Theme.Space.l) {
            Text("Scores")
                .font(Theme.Typography.emphasis)
                .foregroundStyle(Theme.text)

            ScoreCardView(kind: .memory, value: board.memory.overall, updated: board.memory.lastUpdated)
            Text("Memory is your recall on the cards you have reviewed (FSRS retrievability). It abstains until a topic has enough reviews.")
                .font(Theme.Typography.caption)
                .foregroundStyle(Theme.muted)

            ScoreCardView(
                kind: .performance,
                value: board.performance.overall,
                updated: board.performance.lastUpdated
            )
            Text("Performance is your chance on a new, unseen problem, read from the problems you attempt (not cards reviewed). It abstains until a topic has at least \(board.performance.kPerf) attempts.")
                .font(Theme.Typography.caption)
                .foregroundStyle(Theme.muted)

            ScoreCardView(
                kind: .readiness,
                value: board.readiness.scoreValue,
                updated: board.readiness.lastUpdated,
                scale: .scaled,
                howSureDetail: board.readiness.howSureDetail
            )
            Text("Readiness leans on Performance under exam conditions, gated on questions attempted. It abstains until at least \(Int((board.readiness.coverageGate * 100).rounded()))% of the exam has been attempted.")
                .font(Theme.Typography.caption)
                .foregroundStyle(Theme.muted)

            if !board.readiness.abstain, !board.readiness.uncoveredTopics.isEmpty {
                Text("Guessing baseline filled in for: \(board.readiness.uncoveredTopics.map(CategoryLabels.label).joined(separator: ", ")).")
                    .font(Theme.Typography.caption)
                    .foregroundStyle(Theme.muted)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    // MARK: Calibration

    /// The embedded calibration evidence: a reliability diagram plus Brier for
    /// Memory and Performance, from the offline evaluations (calibration_evidence).
    /// Read straight from the engine's embedded constant, so it always renders
    /// offline and never touches the private content/ tree. Mirrors the desktop
    /// Calibration tab: each layer's curve in its reserved hue, the honest note,
    /// and the provenance (n, date, source, method).
    private func calibrationSection() -> some View {
        let evidence = app.engine.calibrationEvidence()
        return VStack(alignment: .leading, spacing: Theme.Space.l) {
            HStack(alignment: .firstTextBaseline) {
                Text("Calibration")
                    .font(Theme.Typography.emphasis)
                    .foregroundStyle(Theme.text)
                Spacer()
                Text("How honest the model is")
                    .font(Theme.Typography.caption)
                    .foregroundStyle(Theme.muted)
            }

            calibrationCell(title: "Memory", read: "Held-out reviews", tone: .memory, layer: evidence.memory)
            Divider().background(Theme.border)
            calibrationCell(title: "Performance", read: "Held-out synthetic", tone: .performance, layer: evidence.performance)

            Text("Calibration compares each model's predicted chance against what actually happened on held-out data. The closer the line sits to the diagonal, the more honest the model.")
                .font(Theme.Typography.caption)
                .foregroundStyle(Theme.muted)
        }
        .padding(Theme.Space.l)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.surface)
        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous)
                .stroke(Theme.border, lineWidth: 1)
        )
    }

    /// One model layer's calibration cell: the layer title in its reserved hue,
    /// the reliability diagram (points mapped from the evidence's {p, o} shape to
    /// the diagram's {predicted, observed} via CalibrationLayer.reliabilityPoints)
    /// with its Brier and honest read, the caption note, and the provenance line
    /// (n, date, source, method). Mirrors the desktop calibView.
    private func calibrationCell(title: String, read: String, tone: ScoreKind, layer: CalibrationLayer) -> some View {
        VStack(alignment: .leading, spacing: Theme.Space.s) {
            Text(title)
                .font(Theme.Typography.emphasis)
                .foregroundStyle(tone.textTint)

            ReliabilityDiagramView(
                points: layer.reliabilityPoints,
                brier: layer.brier,
                read: read,
                tone: tone,
                size: 200
            )

            Text(layer.note)
                .font(Theme.Typography.caption)
                .foregroundStyle(Theme.muted)

            VStack(alignment: .leading, spacing: Theme.Space.xs) {
                Text("n \(Self.formattedCount(layer.n)) · \(layer.date)")
                    .font(Theme.Typography.mono(11))
                    .foregroundStyle(Theme.muted)
                Text(layer.source)
                    .font(Theme.Typography.caption)
                    .foregroundStyle(Theme.muted)
                Text(layer.method)
                    .font(Theme.Typography.caption)
                    .foregroundStyle(Theme.muted)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    /// Group the sample count with thousands separators, matching the desktop's
    /// `toLocaleString("en-US")` (7,503 not 7503).
    private static let countFormatter: NumberFormatter = {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.locale = Locale(identifier: "en_US")
        return formatter
    }()

    private static func formattedCount(_ n: Int) -> String {
        countFormatter.string(from: NSNumber(value: n)) ?? "\(n)"
    }
}
