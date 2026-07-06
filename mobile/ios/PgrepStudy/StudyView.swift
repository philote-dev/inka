// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Study: the Cards door (memory retrieval then reveal then an FSRS grade). It
// mirrors the desktop cards loop on the shared engine, in points-at-stake order
// from the deck config. Real scheduling and revlog; no schedule is hand-edited,
// so this is exactly what syncs to desktop. The Problems door and the
// wrong-answer ladder are a later layer.

import SwiftUI

@MainActor
final class StudyModel: ObservableObject {
    enum Phase: Equatable {
        case loading
        case reviewing(ReviewCard)
        case done
        case failed(String)
    }

    @Published private(set) var phase: Phase = .loading
    @Published var showBack = false
    @Published private(set) var busy = false

    func loadNext(engine: Engine) async {
        showBack = false
        do {
            if let card = try await engine.nextCard() {
                phase = .reviewing(card)
            } else {
                phase = .done
            }
        } catch {
            phase = .failed(String(describing: error))
        }
    }

    func grade(_ grade: Grade, engine: Engine) async {
        guard !busy else { return }
        busy = true
        defer { busy = false }
        do {
            try await engine.answer(grade)
            await loadNext(engine: engine)
        } catch {
            phase = .failed(String(describing: error))
        }
    }
}

struct StudyView: View {
    @EnvironmentObject private var app: AppModel
    @StateObject private var model = StudyModel()

    var body: some View {
        VStack(spacing: Theme.Space.l) {
            content
        }
        .padding(Theme.Space.l)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(Theme.canvas.ignoresSafeArea())
        .task(id: app.dataVersion) { await model.loadNext(engine: app.engine) }
    }

    @ViewBuilder
    private var content: some View {
        switch model.phase {
        case .loading:
            Spacer()
            ProgressView("Opening the queue…")
            Spacer()
        case let .reviewing(card):
            reviewing(card)
        case .done:
            Spacer()
            statusCard(title: "All caught up", message: "No cards are due right now.", tint: Theme.success)
            Button("Check again") { Task { await model.loadNext(engine: app.engine) } }
                .font(Theme.Typography.body)
                .foregroundStyle(Theme.muted)
            Spacer()
        case let .failed(message):
            Spacer()
            statusCard(title: "Something went wrong", message: message, tint: Theme.error)
            Spacer()
        }
    }

    private func reviewing(_ card: ReviewCard) -> some View {
        VStack(spacing: Theme.Space.l) {
            HStack {
                Label("\(card.remaining) in queue", systemImage: "square.stack.3d.up")
                    .font(Theme.Typography.caption)
                    .foregroundStyle(Theme.muted)
                Spacer()
                HStack(spacing: Theme.Space.xs) {
                    Circle().fill(Theme.memory).frame(width: 8, height: 8)
                    Text("Cards").font(Theme.Typography.caption).foregroundStyle(Theme.muted)
                }
            }

            VStack(spacing: Theme.Space.m) {
                MathText(html: card.front, fontSize: 24, weight: .semibold, centered: true)
                    .frame(maxWidth: .infinity)
                if model.showBack {
                    Divider().background(Theme.border)
                    MathText(html: card.back, fontSize: 17, centered: true)
                        .frame(maxWidth: .infinity)
                }
            }
            .frame(maxWidth: .infinity)
            .padding(Theme.Space.xl)
            .background(Theme.surface)
            .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.frame, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: Theme.Radius.frame, style: .continuous)
                    .stroke(Theme.border, lineWidth: 1)
            )

            Spacer()

            if model.showBack {
                gradeBar
            } else {
                Button {
                    model.showBack = true
                } label: {
                    Text("Show answer")
                        .font(Theme.Typography.emphasis)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, Theme.Space.m)
                        .background(Theme.actionBg)
                        .foregroundStyle(Theme.actionFg)
                        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))
                }
            }
        }
    }

    private var gradeBar: some View {
        HStack(spacing: Theme.Space.s) {
            ForEach(Grade.allCases, id: \.rawValue) { grade in
                Button {
                    Task { await model.grade(grade, engine: app.engine) }
                } label: {
                    Text(grade.label)
                        .font(Theme.Typography.body)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, Theme.Space.m)
                        .foregroundStyle(Theme.text)
                        .overlay(
                            RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous)
                                .stroke(Theme.border, lineWidth: 1)
                        )
                }
                .disabled(model.busy)
            }
        }
    }

    private func statusCard(title: String, message: String, tint: Color) -> some View {
        VStack(spacing: Theme.Space.s) {
            Circle().fill(tint).frame(width: 12, height: 12)
            Text(title).font(Theme.Typography.title).foregroundStyle(Theme.text)
            Text(message)
                .font(Theme.Typography.body)
                .foregroundStyle(Theme.muted)
                .multilineTextAlignment(.center)
        }
        .padding(Theme.Space.xl)
        .frame(maxWidth: .infinity)
        .background(Theme.surface)
        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.frame, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: Theme.Radius.frame, style: .continuous)
                .stroke(Theme.border, lineWidth: 1)
        )
    }
}
