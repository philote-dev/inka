// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Home: the readiness glance (design/ux-foundation.md §7.1, mobile subset §9).
// The real 3D knowledge manifold (the same WebGL/Three.js hero as desktop, hosted
// in a WKWebView over the synced Memory), the single Today action, and the three
// scores in one compact above-the-fold row. Practice and Exam live on Study, and
// the full score cards on Progress, matching the desktop Home information model.
// All three scores are computed natively over the shared engine: Memory from FSRS
// retrievability, Performance from the synced attempt log with Memory as the
// mastery bridge, and Readiness projected from Performance. With no attempt data
// yet, Performance and Readiness abstain honestly, never a fabricated number.

import SwiftUI

@MainActor
final class HomeModel: ObservableObject {
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

struct HomeView: View {
    @EnvironmentObject private var app: AppModel
    @Environment(\.colorScheme) private var colorScheme
    @StateObject private var model = HomeModel()
    @Binding var selectedTab: RootTab

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Space.m) {
                if app.diagnosticDone == false {
                    DiagnosticCTA { app.isPresentingDiagnostic = true }
                }
                ManifoldWebView(surface: manifoldSurface, colorScheme: colorScheme)
                    .frame(height: 160)
                today
                scoreRow
                progressLink
            }
            .padding(Theme.Space.l)
        }
        .background(Theme.canvas.ignoresSafeArea())
        .task(id: app.dataVersion) { await model.load(engine: app.engine) }
    }

    /// The live 3D manifold reads the same synced scores the cards do: an area
    /// lights and rises as it is studied (amber -> blue -> lilac as Memory,
    /// Performance, and readiness build), a strong diagnostic area is affirmed,
    /// and a rusty or weak one opens a gap. Before the first read it shows the
    /// honest unlit syllabus, so the hero is never blank.
    private var manifoldSurface: ManifoldSurface {
        if case let .loaded(board) = model.state {
            return ManifoldSurface.build(
                memory: board.memory,
                performance: board.performance,
                placement: board.placement
            )
        }
        return .baseline
    }

    /// The three scores in one compact row so all three read above the fold on a
    /// standard device, no scrolling. The full cards live on Progress.
    @ViewBuilder
    private var scoreRow: some View {
        HStack(alignment: .top, spacing: Theme.Space.s) {
            switch model.state {
            case .loading:
                CompactScoreCard(kind: .memory, value: .abstaining(""), loading: true)
                CompactScoreCard(kind: .performance, value: .abstaining(""), loading: true)
                CompactScoreCard(kind: .readiness, value: .abstaining(""), scale: .scaled, loading: true)
            case let .loaded(board):
                CompactScoreCard(kind: .memory, value: board.memory.overall)
                CompactScoreCard(kind: .performance, value: board.performance.overall)
                CompactScoreCard(kind: .readiness, value: board.readiness.scoreValue, scale: .scaled)
            case .failed:
                CompactScoreCard(kind: .memory, value: .abstaining("--"))
                CompactScoreCard(kind: .performance, value: .abstaining("--"))
                CompactScoreCard(kind: .readiness, value: .abstaining("--"), scale: .scaled)
            }
        }
    }

    private var progressLink: some View {
        Button {
            selectedTab = .progress
        } label: {
            HStack {
                Text("See full progress")
                    .font(Theme.Typography.emphasis)
                    .foregroundStyle(Theme.text)
                Spacer()
                Image(systemName: "chevron.right")
                    .font(Theme.Typography.body)
                    .foregroundStyle(Theme.muted)
            }
            .padding(Theme.Space.l)
            .background(Theme.surface)
            .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous)
                    .stroke(Theme.border, lineWidth: 1)
            )
        }
    }

    private var today: some View {
        VStack(alignment: .leading, spacing: Theme.Space.m) {
            HStack(spacing: Theme.Space.s) {
                Image(systemName: "play")
                    .font(.system(size: 13))
                    .foregroundStyle(Theme.text)
                    .accessibilityHidden(true)
                Text("Today")
                    .font(Theme.Typography.emphasis)
                    .foregroundStyle(Theme.text)
            }
            Text("Cards and problems, interleaved")
                .font(Theme.Typography.body)
                .foregroundStyle(Theme.muted)
            Button {
                selectedTab = .study
            } label: {
                Text("Start session")
                    .font(Theme.Typography.emphasis)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, Theme.Space.m)
                    .background(Theme.actionBg)
                    .foregroundStyle(Theme.actionFg)
                    .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(Theme.Space.l)
        .background(Theme.surface)
        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous)
                .stroke(Theme.border, lineWidth: 1)
        )
    }
}
