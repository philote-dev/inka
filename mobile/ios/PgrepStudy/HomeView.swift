// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Home: the readiness glance (design/ux-foundation.md §7.1, mobile subset §9).
// The manifold thumbnail, a Today action, and the three score cards. All three
// are computed natively over the shared engine: Memory from FSRS retrievability,
// Performance from the synced attempt log with Memory as the mastery bridge, and
// Readiness projected from Performance. When there is no attempt data yet (a
// phone that has not synced problem work), Performance and Readiness abstain
// honestly for the right reason, never a fabricated number, exactly like desktop.

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
    @StateObject private var model = HomeModel()
    @Binding var selectedTab: RootTab
    @State private var showExam = false
    @State private var showLadder = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Space.l) {
                greeting
                ManifoldThumbnail()
                    .frame(height: 190)
                today
                scoreCards
                progressLink
            }
            .padding(Theme.Space.l)
        }
        .background(Theme.canvas.ignoresSafeArea())
        .task(id: app.dataVersion) { await model.load(engine: app.engine) }
        .fullScreenCover(isPresented: $showExam) {
            ExamView().environmentObject(app)
        }
        .fullScreenCover(isPresented: $showLadder) {
            LadderView().environmentObject(app)
        }
    }

    @ViewBuilder
    private var scoreCards: some View {
        switch model.state {
        case .loading:
            loadingCard
        case let .loaded(board):
            ScoreCardView(kind: .memory, value: board.memory.overall, updated: board.memory.lastUpdated)
            ScoreCardView(
                kind: .performance,
                value: board.performance.overall,
                updated: board.performance.lastUpdated
            )
            ScoreCardView(
                kind: .readiness,
                value: board.readiness.scoreValue,
                updated: board.readiness.lastUpdated,
                scale: .scaled,
                howSureDetail: board.readiness.howSureDetail
            )
        case let .failed(message):
            ScoreCardView(kind: .memory, value: .abstaining("Could not read the collection"), updated: nil)
            ScoreCardView(kind: .performance, value: .abstaining(message), updated: nil)
            ScoreCardView(kind: .readiness, value: .abstaining(message), updated: nil, scale: .scaled)
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

    private var greeting: some View {
        VStack(alignment: .leading, spacing: Theme.Space.xs) {
            Text("pgrep")
                .font(Theme.Typography.greeting)
                .foregroundStyle(Theme.text)
            Text("Your readiness at a glance.")
                .font(Theme.Typography.body)
                .foregroundStyle(Theme.muted)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var today: some View {
        VStack(alignment: .leading, spacing: Theme.Space.m) {
            Text("Today")
                .font(Theme.Typography.emphasis)
                .foregroundStyle(Theme.text)
            Text("One interleaved session, in points-at-stake order.")
                .font(Theme.Typography.body)
                .foregroundStyle(Theme.muted)
            Button {
                selectedTab = .study
            } label: {
                Text("Start today's session")
                    .font(Theme.Typography.emphasis)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, Theme.Space.m)
                    .background(Theme.actionBg)
                    .foregroundStyle(Theme.actionFg)
                    .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))
            }
            Button {
                showLadder = true
            } label: {
                Text("Practice problems")
                    .font(Theme.Typography.emphasis)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, Theme.Space.m)
                    .foregroundStyle(Theme.text)
                    .overlay(
                        RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous)
                            .stroke(Theme.border, lineWidth: 1)
                    )
            }
            Button {
                showExam = true
            } label: {
                Text("Take a timed exam")
                    .font(Theme.Typography.emphasis)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, Theme.Space.m)
                    .foregroundStyle(Theme.text)
                    .overlay(
                        RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous)
                            .stroke(Theme.border, lineWidth: 1)
                    )
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

    private var loadingCard: some View {
        HStack(spacing: Theme.Space.m) {
            Circle().fill(Theme.memory).frame(width: 10, height: 10)
            Text("Reading your collection")
                .font(Theme.Typography.emphasis)
                .foregroundStyle(Theme.text)
            Spacer()
            ProgressView()
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
