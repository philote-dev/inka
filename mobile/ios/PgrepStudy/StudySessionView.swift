// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// The interleaved study session surface (today's session), the phone's primary
// study path. It weaves the Cards door (real FSRS review then reveal then grade)
// and the Problems door (commit BEFORE any help) into one queue, mirroring the
// desktop launcher (ts/routes/pgrep/study/+page.svelte) and the two-door loop in
// pylib/anki/pgrep/study.py. The interleave order and the commit grading live in
// the pure StudySession core; this file drives them against the shared Engine.
//
// Cards run the genuine scheduler loop (Engine.nextCard/answer): real reviews,
// real revlog, so the schedule that syncs to desktop is untouched. Problems come
// from the seeded bank in study.py rotation order (Engine.loadLadderProblems),
// and each commit appends one immutable Attempt (ladder_depth 0) through the
// write path, so a phone session feeds Performance/Readiness through the same
// fold as desktop. A hit affirms the picked choice; a miss reveals the correct
// choice and the stored worked solution (the seam the gated decomposition tutor
// replaces next).

import SwiftUI

/// The committed outcome for one problem, built locally from stored data (AI
/// off). On a miss `steps` carries the worked solution to reveal; on a hit it is
/// empty (the affirmed correct choice is enough).
struct StudyReveal: Equatable {
    var correct: Bool
    var correctLetter: String
    var steps: [LadderStep]
}

@MainActor
final class StudySessionModel: ObservableObject {
    enum Phase: Equatable {
        case loading
        case card(ReviewCard)
        case problem(LadderProblem)
        case done
        case failed(String)
    }

    @Published private(set) var phase: Phase = .loading
    @Published var showBack = false
    @Published private(set) var selected = ""
    @Published private(set) var committed: StudyReveal?
    @Published private(set) var busy = false

    // Recap counters. Honest by construction: real card reviews and real
    // committed first-try attempts, nothing inferred.
    @Published private(set) var cardsReviewed = 0
    @Published private(set) var problemsCommitted = 0
    @Published private(set) var problemsCorrect = 0
    @Published private(set) var startedEmpty = false

    private var engine: Engine?
    private var onPersisted: (() -> Void)?
    private var hasStarted = false
    private var problems: [LadderProblem] = []
    private var problemIndex = 0
    private var servedCards = 0
    private var sessionId = UUID().uuidString
    // When the current problem was shown, for the response-time signal (M5).
    private var problemShownAt = Date()

    var problemsTotal: Int { problems.count }
    /// Problems still queued behind the current one (the shown item has already
    /// left the queue). Drives the interleave and the "N left" chrome.
    var problemsRemaining: Int { max(0, problems.count - problemIndex) }
    /// The 1-based number of the problem on screen (0 when none is showing).
    var currentProblemNumber: Int { problemIndex }

    /// Start the sitting once. Idempotent across tab reappearance, so switching
    /// away and back never discards a session in progress. Use `restart` for a
    /// fresh sitting from the recap.
    func startIfNeeded(engine: Engine, onPersisted: @escaping () -> Void) async {
        self.engine = engine
        self.onPersisted = onPersisted
        guard !hasStarted else { return }
        await beginSitting()
    }

    /// Run a fresh sitting (from the recap's Start again / Check again).
    func restart() async {
        await beginSitting()
    }

    private func beginSitting() async {
        guard let engine else { return }
        hasStarted = true
        phase = .loading
        problemIndex = 0
        servedCards = 0
        cardsReviewed = 0
        problemsCommitted = 0
        problemsCorrect = 0
        startedEmpty = false
        sessionId = UUID().uuidString
        do {
            // The seeded problem bank in study.py rotation order, capped to a
            // sitting (reuses the loader Ladder uses).
            problems = try await engine.loadLadderProblems()
            await loadNext(firstItem: true)
        } catch {
            phase = .failed(String(describing: error))
        }
    }

    /// Weave and present the next item. Peeks the scheduler's top card (a repeat
    /// peek is idempotent while the card is unanswered), then lets StudySession
    /// choose card or problem from the live counts.
    private func loadNext(firstItem: Bool = false) async {
        guard let engine else { return }
        busy = true
        defer { busy = false }
        showBack = false
        selected = ""
        committed = nil
        do {
            let card = try await engine.nextCard()
            let kind = StudySession.nextKind(
                cardsAvailable: card != nil,
                cardsRemaining: card?.remaining ?? 0,
                servedCards: servedCards,
                problemsRemaining: problemsRemaining,
                servedProblems: problemIndex
            )
            switch kind {
            case .none:
                if firstItem { startedEmpty = true }
                phase = .done
            case .card:
                // cardsAvailable was true, so the card is present.
                if let card { phase = .card(card) } else { phase = .done }
            case .problem:
                let problem = problems[problemIndex]
                problemIndex += 1
                problemShownAt = Date()
                phase = .problem(problem)
            }
        } catch {
            phase = .failed(String(describing: error))
        }
    }

    func revealAnswer() { showBack = true }

    func select(_ letter: String) {
        guard committed == nil else { return }
        selected = letter
    }

    /// Grade a card through the real FSRS loop, then weave the next item.
    func grade(_ grade: Grade) async {
        guard case .card = phase, let engine, !busy else { return }
        busy = true
        do {
            try await engine.answer(grade)
            servedCards += 1
            cardsReviewed += 1
        } catch {
            phase = .failed(String(describing: error))
            busy = false
            return
        }
        await loadNext()
    }

    /// The commit gate: grade locally, append one clean Attempt (ladder_depth 0),
    /// then reveal. A hit affirms the picked choice; a miss reveals the correct
    /// choice (through the ChoiceList) and the stored worked solution.
    func commit() {
        guard case let .problem(problem) = phase, committed == nil, !selected.isEmpty else { return }
        let correct = StudySession.isCorrect(selected: selected, correctLetter: problem.correctLetter)
        committed = StudyReveal(
            correct: correct,
            correctLetter: problem.correctLetter.uppercased(),
            steps: StudySession.revealSteps(correct: correct, solutionSteps: problem.decomposition)
        )
        problemsCommitted += 1
        if correct { problemsCorrect += 1 }
        persistAttempt(problem: problem, correct: correct)
    }

    /// Move on from a committed problem to the next woven item.
    func advance() async {
        await loadNext()
    }

    /// Persist one clean Attempt for the committed problem, then ask Home /
    /// Progress to recompute. Mirrors the Ladder/Exam write path exactly.
    private func persistAttempt(problem: LadderProblem, correct: Bool) {
        guard let engine else { return }
        let responseMs = Int(max(0, Date().timeIntervalSince(problemShownAt) * 1000))
        let draft = AttemptDraft(
            itemNoteId: problem.noteId,
            topic: problem.topic,
            category: problem.category,
            correct: correct,
            selectedOption: selected,
            sessionId: sessionId,
            answeredAt: Int(Date().timeIntervalSince1970),
            ladderDepth: 0,
            difficulty: problem.difficulty,
            responseMs: responseMs
        )
        Task { @MainActor [weak self] in
            try? await engine.logAttempts([draft])
            self?.onPersisted?()
        }
    }
}

struct StudySessionView: View {
    @EnvironmentObject private var app: AppModel
    @StateObject private var model = StudySessionModel()

    var body: some View {
        content
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            .task {
                await model.startIfNeeded(engine: app.engine, onPersisted: { app.refreshScores() })
            }
    }

    @ViewBuilder
    private var content: some View {
        switch model.phase {
        case .loading:
            centered { ProgressView("Building today's session…") }
        case let .card(card):
            cardView(card)
        case let .problem(problem):
            problemView(problem)
        case .done:
            doneView
        case let .failed(message):
            centered { statusCard(title: "Something went wrong", message: message, tint: Theme.error) }
        }
    }

    // MARK: Cards door

    private func cardView(_ card: ReviewCard) -> some View {
        VStack(spacing: Theme.Space.l) {
            itemHeader(kind: .card, trailing: "\(card.remaining) in queue")

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
                Text("How well did you remember it?")
                    .font(Theme.Typography.caption)
                    .foregroundStyle(Theme.muted)
                gradeBar
            } else {
                Button {
                    model.revealAnswer()
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
                    Task { await model.grade(grade) }
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

    // MARK: Problems door (commit before help)

    private func problemView(_ problem: LadderProblem) -> some View {
        VStack(spacing: Theme.Space.m) {
            itemHeader(
                kind: .problem,
                trailing: "Problem \(model.currentProblemNumber) of \(model.problemsTotal)"
            )
            ScrollView {
                VStack(alignment: .leading, spacing: Theme.Space.l) {
                    MathText(html: problem.stem, fontSize: 17)
                        .frame(maxWidth: .infinity, alignment: .leading)

                    ChoiceListView(
                        choices: ChoiceList.lettered(problem.choices),
                        selected: Binding(
                            get: { model.selected.isEmpty ? nil : model.selected },
                            set: { picked in if let picked { model.select(picked) } }
                        ),
                        committed: model.committed != nil,
                        correctKey: model.committed?.correctLetter
                    )

                    if let committed = model.committed {
                        feedback(committed)
                    } else {
                        commitBar
                    }
                }
                .padding(.bottom, Theme.Space.l)
            }
        }
    }

    private var commitBar: some View {
        VStack(alignment: .leading, spacing: Theme.Space.s) {
            Button {
                model.commit()
            } label: {
                Text("Commit")
                    .font(Theme.Typography.emphasis)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, Theme.Space.m)
                    .background(model.selected.isEmpty ? Theme.elevated : Theme.actionBg)
                    .foregroundStyle(model.selected.isEmpty ? Theme.muted : Theme.actionFg)
                    .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))
            }
            .disabled(model.selected.isEmpty || model.busy)
            Text("Help stays locked until you commit.")
                .font(Theme.Typography.caption)
                .foregroundStyle(Theme.muted)
        }
    }

    private func feedback(_ committed: StudyReveal) -> some View {
        VStack(alignment: .leading, spacing: Theme.Space.m) {
            Text(committed.correct ? "Correct." : "Not correct.")
                .font(Theme.Typography.emphasis)
                .foregroundStyle(committed.correct ? Theme.success : Theme.performanceText)

            // Miss seam: a problem carrying decomposition-tutor data opens the
            // gated tutor here in the next task. For now, reveal the worked
            // solution so a miss never strands the learner.
            if !committed.correct, !committed.steps.isEmpty {
                SolutionRevealView(steps: committed.steps)
            }

            nextBar
        }
    }

    private var nextBar: some View {
        HStack {
            Button {
                Task { await model.advance() }
            } label: {
                Text("Next")
                    .font(Theme.Typography.emphasis)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, Theme.Space.m)
                    .background(Theme.actionBg)
                    .foregroundStyle(Theme.actionFg)
                    .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))
            }
            .disabled(model.busy)
        }
        .padding(.top, Theme.Space.s)
        .overlay(alignment: .topLeading) {
            if model.problemsRemaining > 0 {
                Text("\(model.problemsRemaining) problems left")
                    .font(Theme.Typography.caption)
                    .foregroundStyle(Theme.muted)
                    .offset(y: -Theme.Space.m)
            }
        }
    }

    // MARK: Recap

    private var doneView: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Space.l) {
                if model.startedEmpty {
                    statusCard(
                        title: "All caught up",
                        message: "No cards are due and there is nothing to practice right now.",
                        tint: Theme.success
                    )
                } else {
                    Text("Session complete")
                        .font(Theme.Typography.title)
                        .foregroundStyle(Theme.text)
                    VStack(alignment: .leading, spacing: Theme.Space.s) {
                        summaryRow("Cards reviewed", "\(model.cardsReviewed)")
                        summaryRow("Problems committed", "\(model.problemsCommitted)")
                        summaryRow("First-try correct", "\(model.problemsCorrect)")
                        if model.problemsCommitted > 0 {
                            summaryRow(
                                "Accuracy",
                                "\(Int((Double(model.problemsCorrect) / Double(model.problemsCommitted) * 100).rounded()))%"
                            )
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
                    Text("Your committed answers feed Performance and Readiness, once a topic has enough attempts.")
                        .font(Theme.Typography.caption)
                        .foregroundStyle(Theme.muted)
                }

                Button {
                    Task { await model.restart() }
                } label: {
                    Text(model.startedEmpty ? "Check again" : "Start again")
                        .font(Theme.Typography.emphasis)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, Theme.Space.m)
                        .background(Theme.actionBg)
                        .foregroundStyle(Theme.actionFg)
                        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))
                }
            }
            .padding(.bottom, Theme.Space.l)
        }
    }

    // MARK: Shared chrome

    private func itemHeader(kind: StudyItemKind, trailing: String) -> some View {
        HStack {
            HStack(spacing: Theme.Space.xs) {
                Circle()
                    .fill(kind == .card ? Theme.memory : Theme.performance)
                    .frame(width: 8, height: 8)
                Text(kind == .card ? "Cards" : "Problems")
                    .font(Theme.Typography.caption)
                    .foregroundStyle(Theme.muted)
            }
            Spacer()
            Text(trailing)
                .font(Theme.Typography.caption)
                .foregroundStyle(Theme.muted)
        }
    }

    private func centered<Inner: View>(@ViewBuilder _ inner: () -> Inner) -> some View {
        VStack {
            Spacer()
            inner()
            Spacer()
        }
    }

    private func summaryRow(_ label: String, _ value: String) -> some View {
        HStack {
            Text(label).font(Theme.Typography.body).foregroundStyle(Theme.muted)
            Spacer()
            Text(value).font(Theme.Typography.mono(14)).foregroundStyle(Theme.text)
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

/// The worked-solution reveal shown after a miss on a problem with no gated
/// decomposition, a native port of ts/lib/components/SolutionReveal.svelte. It
/// walks the stored solution steps (each a sub-goal and its rubric) so the
/// learner leaves with the idea. Presentational: steps arrive as data.
struct SolutionRevealView: View {
    let steps: [LadderStep]
    var heading = "Here's how it works"

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Space.s) {
            Text("Worked solution")
                .font(Theme.Typography.caption)
                .textCase(.uppercase)
                .foregroundStyle(Theme.muted)
            Text(heading)
                .font(Theme.Typography.emphasis)
                .foregroundStyle(Theme.text)
            VStack(alignment: .leading, spacing: Theme.Space.m) {
                ForEach(Array(steps.enumerated()), id: \.offset) { pair in
                    stepRow(number: pair.offset + 1, step: pair.element)
                }
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

    private func stepRow(number: Int, step: LadderStep) -> some View {
        HStack(alignment: .top, spacing: Theme.Space.m) {
            Text("\(number)")
                .font(Theme.Typography.mono(12))
                .foregroundStyle(Theme.muted)
                .frame(width: 24, height: 24)
                .overlay(Circle().stroke(Theme.border, lineWidth: 1))
            VStack(alignment: .leading, spacing: Theme.Space.xs) {
                if !step.subgoal.isEmpty {
                    Text(step.subgoal)
                        .font(Theme.Typography.emphasis)
                        .foregroundStyle(Theme.text)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                if !step.rubric.isEmpty {
                    MathText(html: step.rubric, fontSize: 15)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
    }
}
