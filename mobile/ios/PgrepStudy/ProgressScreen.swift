// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Progress: the coverage ledger and the three score cards for the mobile
// companion, mirroring the desktop Progress surface
// (ts/routes/pgrep/progress/+page.svelte, the Coverage + Scores tabs). Coverage
// shows how much of the blueprint has a reviewed card (a segmented bar per
// category, the overall fraction against the Readiness gate, and a per-category
// list reusing each topic's Memory point). The three cards then read Memory,
// Performance, and Readiness with their 80% ranges, each abstaining honestly on
// thin data. All computed natively over the shared engine, the same snapshot
// Home reads. The Calibration tab (embedded offline evidence) is desktop-first.

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

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Space.l) {
                header
                content
            }
            .padding(Theme.Space.l)
        }
        .background(Theme.canvas.ignoresSafeArea())
        .task(id: app.dataVersion) { await model.load(engine: app.engine) }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: Theme.Space.xs) {
            Text("Progress")
                .font(Theme.Typography.greeting)
                .foregroundStyle(Theme.text)
            Text("Coverage gates Readiness. Each score abstains until the evidence is there.")
                .font(Theme.Typography.body)
                .foregroundStyle(Theme.muted)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private var content: some View {
        switch model.state {
        case .loading:
            ProgressView("Reading your coverage…")
                .frame(maxWidth: .infinity, minHeight: 200)
        case let .loaded(board):
            coveragePanel(board.coverage)
            scoresSection(board)
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
}
