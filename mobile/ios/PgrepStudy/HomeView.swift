// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Home: the readiness glance (design/ux-foundation.md §7.1, mobile subset §9).
// The manifold thumbnail, a Today action, and the three score cards. Memory is
// computed natively over the shared engine; Performance and Readiness abstain
// honestly until the L5 models exist, exactly like desktop.

import SwiftUI

@MainActor
final class HomeModel: ObservableObject {
    enum LoadState: Equatable {
        case loading
        case loaded(MemoryResult)
        case failed(String)
    }

    @Published private(set) var state: LoadState = .loading

    func load(engine: Engine) async {
        state = .loading
        do {
            state = .loaded(try await engine.computeMemory())
        } catch {
            state = .failed(String(describing: error))
        }
    }
}

struct HomeView: View {
    @EnvironmentObject private var app: AppModel
    @StateObject private var model = HomeModel()
    @Binding var selectedTab: RootTab

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Space.l) {
                greeting
                ManifoldThumbnail()
                    .frame(height: 190)
                today
                memoryCard
                ScoreCardView(kind: .performance, value: .abstaining("No performance model yet"), updated: nil)
                ScoreCardView(kind: .readiness, value: .abstaining("Needs a performance model and 70% coverage"), updated: nil)
            }
            .padding(Theme.Space.l)
        }
        .background(Theme.canvas.ignoresSafeArea())
        .task(id: app.dataVersion) { await model.load(engine: app.engine) }
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

    @ViewBuilder
    private var memoryCard: some View {
        switch model.state {
        case .loading:
            loadingCard
        case let .loaded(result):
            ScoreCardView(kind: .memory, value: result.overall, updated: result.lastUpdated)
        case .failed:
            ScoreCardView(
                kind: .memory,
                value: .abstaining("Could not read the collection"),
                updated: nil
            )
        }
    }

    private var loadingCard: some View {
        HStack(spacing: Theme.Space.m) {
            Circle().fill(Theme.memory).frame(width: 10, height: 10)
            Text("Memory")
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
