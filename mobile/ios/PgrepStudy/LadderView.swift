// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// The Problems door on iOS: the wrong-answer ladder (productive failure),
// mirroring the desktop Study surface (ts/routes/pgrep/study/+page.svelte and
// pylib/anki/pgrep/study.py commit_problem). The learner commits an answer
// BEFORE any help (the commit gate), which appends exactly one immutable Attempt
// (ladder_depth 0, the honest first-try signal) through the write path, then a
// static four-rung ladder built from the item's stored solution_decomposition
// (nudge -> decompose -> sibling -> reveal). The final answer appears only in the
// reveal rung. No AI, no confidence capture.
//
// The attempts this logs feed Home's Performance/Readiness through the same fold
// as the exam and desktop. Response time (item shown -> commit) rides into the
// payload so rapid guesses can be filtered, exactly like desktop's M5 seam.

import SwiftUI

@MainActor
final class LadderModel: ObservableObject {
    enum Phase: Equatable {
        case loading
        case empty
        case running
        case done
        case failed(String)
    }

    /// The committed feedback for the current problem (built locally from stored
    /// data, so the ladder is AI-off): correctness, the rationale, and the rungs.
    struct Committed: Equatable {
        var correct: Bool
        var rationaleHTML: String
        var rungs: [LadderRung]
    }

    @Published private(set) var phase: Phase = .loading
    @Published private(set) var problems: [LadderProblem] = []
    @Published private(set) var index = 0
    @Published var selected: String = ""
    @Published private(set) var committed: Committed?
    @Published private(set) var revealedRungs = 0
    @Published private(set) var shownReveals: Set<String> = []

    // Session recap.
    @Published private(set) var attempted = 0
    @Published private(set) var correctCount = 0

    private var engine: Engine?
    private var onPersisted: (() -> Void)?
    private var sessionId = UUID().uuidString
    // When the current problem was shown, for the response-time signal.
    private var shownAt = Date()

    var current: LadderProblem? {
        problems.indices.contains(index) ? problems[index] : nil
    }

    var remaining: Int { max(0, problems.count - index - 1) }

    func start(engine: Engine, onPersisted: @escaping () -> Void) async {
        self.engine = engine
        self.onPersisted = onPersisted
        self.sessionId = UUID().uuidString
        phase = .loading
        do {
            let loaded = try await engine.loadLadderProblems()
            guard !loaded.isEmpty else {
                phase = .empty
                return
            }
            problems = loaded
            index = 0
            resetItemState()
            phase = .running
        } catch {
            phase = .failed(String(describing: error))
        }
    }

    func select(_ letter: String) {
        guard committed == nil else { return }
        selected = letter
    }

    /// The commit gate: grade locally, append one clean Attempt (ladder_depth 0),
    /// then open the ladder. On a miss it opens at the first rung; on a hit it
    /// stays closed behind an opt-in "show the worked solution".
    func commit() {
        guard let problem = current, committed == nil, !selected.isEmpty else { return }
        let isCorrect = selected.uppercased() == problem.correctLetter.uppercased()
        committed = Committed(
            correct: isCorrect,
            rationaleHTML: Ladder.rationaleHTML(
                correct: isCorrect,
                selectedLetter: selected,
                rationales: problem.rationales
            ),
            rungs: Ladder.build(for: problem)
        )
        revealedRungs = isCorrect ? 0 : 1
        attempted += 1
        if isCorrect { correctCount += 1 }
        persistAttempt(problem: problem, correct: isCorrect)
    }

    func nextRung() {
        guard let committed else { return }
        if revealedRungs < committed.rungs.count { revealedRungs += 1 }
    }

    func showReveal(_ rung: LadderRung) {
        shownReveals.insert(rung.id)
    }

    /// Jump straight to the worked solution (used on a hit): reveal all rungs and
    /// open the reveal rung's solution.
    func openSolution() {
        guard let committed else { return }
        revealedRungs = committed.rungs.count
        if let reveal = committed.rungs.first(where: { $0.kind == .reveal }) {
            shownReveals.insert(reveal.id)
        }
    }

    func next() {
        guard !problems.isEmpty else { return }
        if index >= problems.count - 1 {
            phase = .done
            return
        }
        index += 1
        resetItemState()
    }

    private func resetItemState() {
        selected = ""
        committed = nil
        revealedRungs = 0
        shownReveals = []
        shownAt = Date()
    }

    private func persistAttempt(problem: LadderProblem, correct: Bool) {
        guard let engine else { return }
        let responseMs = Int(max(0, Date().timeIntervalSince(shownAt) * 1000))
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

struct LadderView: View {
    @EnvironmentObject private var app: AppModel
    @Environment(\.dismiss) private var dismiss
    @StateObject private var model = LadderModel()

    var body: some View {
        NavigationStack {
            content
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                .background(Theme.canvas.ignoresSafeArea())
                .navigationTitle("Problems")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button(model.phase == .done ? "Done" : "Close") { dismiss() }
                    }
                }
        }
        .task { await model.start(engine: app.engine, onPersisted: { app.refreshScores() }) }
    }

    @ViewBuilder
    private var content: some View {
        switch model.phase {
        case .loading:
            centered { ProgressView("Loading problems…") }
        case .empty:
            centered {
                statusCard(
                    title: "No problems yet",
                    message: "This collection has no problem bank. Sync from desktop to load problems, then work the ladder.",
                    tint: Theme.caution
                )
            }
        case .running:
            runningView
        case .done:
            doneView
        case let .failed(message):
            centered { statusCard(title: "Something went wrong", message: message, tint: Theme.error) }
        }
    }

    // MARK: Running

    @ViewBuilder
    private var runningView: some View {
        if let problem = model.current {
            VStack(spacing: Theme.Space.m) {
                header(problem)
                ScrollView {
                    VStack(alignment: .leading, spacing: Theme.Space.l) {
                        problemCard(problem)
                        if model.committed == nil {
                            commitBar
                        } else if let committed = model.committed {
                            feedback(committed)
                        }
                    }
                    .padding(.bottom, Theme.Space.l)
                }
            }
            .padding(Theme.Space.l)
        } else {
            centered { statusCard(title: "No problem", message: "Nothing to show.", tint: Theme.caution) }
        }
    }

    private func header(_ problem: LadderProblem) -> some View {
        HStack {
            HStack(spacing: Theme.Space.xs) {
                Circle().fill(Theme.performance).frame(width: 8, height: 8)
                Text(CategoryLabels.label(problem.category))
                    .font(Theme.Typography.caption)
                    .foregroundStyle(Theme.muted)
            }
            Spacer()
            Text("Problem \(model.index + 1) of \(model.problems.count)")
                .font(Theme.Typography.caption)
                .foregroundStyle(Theme.muted)
        }
    }

    private func problemCard(_ problem: LadderProblem) -> some View {
        VStack(alignment: .leading, spacing: Theme.Space.l) {
            MathText(html: problem.stem, fontSize: 17)
                .frame(maxWidth: .infinity, alignment: .leading)
            choiceList(problem)
        }
        .padding(Theme.Space.l)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.surface)
        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.frame, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: Theme.Radius.frame, style: .continuous)
                .stroke(Theme.border, lineWidth: 1)
        )
    }

    private func choiceList(_ problem: LadderProblem) -> some View {
        VStack(spacing: Theme.Space.s) {
            ForEach(Array(problem.choices.enumerated()), id: \.offset) { pair in
                let letter = pair.offset < examChoiceLetters.count ? examChoiceLetters[pair.offset] : "?"
                choiceRow(letter: letter, text: pair.element, problem: problem)
            }
        }
    }

    private func choiceRow(letter: String, text: String, problem: LadderProblem) -> some View {
        let state = choiceState(letter: letter, problem: problem)
        return Button {
            model.select(letter)
        } label: {
            HStack(alignment: .top, spacing: Theme.Space.m) {
                Text(letter)
                    .font(Theme.Typography.mono(14, weight: .semibold))
                    .foregroundStyle(state.badgeFg)
                    .frame(width: 26, height: 26)
                    .background(state.badgeBg)
                    .clipShape(Circle())
                    .overlay(Circle().stroke(Theme.border, lineWidth: state.badgeBg == .clear ? 1 : 0))
                MathText(html: text, fontSize: 14)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(Theme.Space.m)
            .frame(maxWidth: .infinity, alignment: .leading)
            .overlay(
                RoundedRectangle(cornerRadius: Theme.Radius.row, style: .continuous)
                    .stroke(state.borderColor, lineWidth: state.borderWidth)
            )
        }
        .disabled(model.committed != nil)
    }

    private struct ChoiceStyle {
        var badgeFg: Color
        var badgeBg: Color
        var borderColor: Color
        var borderWidth: CGFloat
    }

    private func choiceState(letter: String, problem: LadderProblem) -> ChoiceStyle {
        let isSelected = model.selected == letter
        guard let committed = model.committed else {
            return ChoiceStyle(
                badgeFg: isSelected ? Theme.actionFg : Theme.text,
                badgeBg: isSelected ? Theme.actionBg : .clear,
                borderColor: isSelected ? Theme.text : Theme.border,
                borderWidth: isSelected ? 2 : 1
            )
        }
        // After commit: mark the correct choice, and a wrong committed choice.
        let isCorrect = letter.uppercased() == problem.correctLetter.uppercased()
        if isCorrect {
            return ChoiceStyle(badgeFg: .white, badgeBg: Theme.success, borderColor: Theme.success, borderWidth: 2)
        }
        if isSelected, !committed.correct {
            return ChoiceStyle(badgeFg: .white, badgeBg: Theme.error, borderColor: Theme.error, borderWidth: 2)
        }
        return ChoiceStyle(badgeFg: Theme.muted, badgeBg: .clear, borderColor: Theme.border, borderWidth: 1)
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
            .disabled(model.selected.isEmpty)
            Text("Help stays locked until you commit.")
                .font(Theme.Typography.caption)
                .foregroundStyle(Theme.muted)
        }
    }

    // MARK: Feedback + ladder

    private func feedback(_ committed: LadderModel.Committed) -> some View {
        VStack(alignment: .leading, spacing: Theme.Space.m) {
            Text(committed.correct ? "Correct." : "Your answer, not correct.")
                .font(Theme.Typography.emphasis)
                .foregroundStyle(committed.correct ? Theme.success : Theme.performanceText)

            MathText(html: committed.rationaleHTML, fontSize: 14)
                .frame(maxWidth: .infinity, alignment: .leading)

            if committed.correct, model.revealedRungs == 0 {
                Button {
                    model.openSolution()
                } label: {
                    Text("Show the worked solution")
                        .font(Theme.Typography.body)
                        .foregroundStyle(Theme.text)
                        .padding(.vertical, Theme.Space.s)
                        .padding(.horizontal, Theme.Space.m)
                        .overlay(
                            RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous)
                                .stroke(Theme.border, lineWidth: 1)
                        )
                }
            }

            if model.revealedRungs > 0 {
                VStack(spacing: Theme.Space.m) {
                    ForEach(Array(committed.rungs.prefix(model.revealedRungs).enumerated()), id: \.offset) { pair in
                        rungCard(pair.element, number: pair.offset + 1, total: committed.rungs.count)
                    }
                }
                if model.revealedRungs < committed.rungs.count {
                    Button {
                        model.nextRung()
                    } label: {
                        Text("Next step")
                            .font(Theme.Typography.body)
                            .foregroundStyle(Theme.text)
                            .padding(.vertical, Theme.Space.s)
                            .padding(.horizontal, Theme.Space.m)
                            .overlay(
                                RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous)
                                    .stroke(Theme.border, lineWidth: 1)
                            )
                    }
                }
                Text("Working it out yourself is the point.")
                    .font(Theme.Typography.caption)
                    .foregroundStyle(Theme.muted)
            }

            nextBar
        }
    }

    private func rungCard(_ rung: LadderRung, number: Int, total: Int) -> some View {
        VStack(alignment: .leading, spacing: Theme.Space.s) {
            HStack {
                Text(rung.kind.title)
                    .font(Theme.Typography.emphasis)
                    .foregroundStyle(Theme.text)
                Spacer()
                Text("\(number) of \(total)")
                    .font(Theme.Typography.mono(12))
                    .foregroundStyle(Theme.muted)
            }
            Text(rung.prompt)
                .font(Theme.Typography.body)
                .foregroundStyle(Theme.muted)
                .frame(maxWidth: .infinity, alignment: .leading)
            if let reveal = rung.revealHTML {
                if model.shownReveals.contains(rung.id) {
                    MathText(html: reveal, fontSize: 14)
                        .frame(maxWidth: .infinity, alignment: .leading)
                } else {
                    Button {
                        model.showReveal(rung)
                    } label: {
                        Text(rung.kind == .reveal ? "Show the solution" : "Show the stored steps")
                            .font(Theme.Typography.body)
                            .foregroundStyle(Theme.performanceText)
                    }
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

    private var nextBar: some View {
        HStack {
            Button {
                model.next()
            } label: {
                Text(model.remaining > 0 ? "Next" : "Finish")
                    .font(Theme.Typography.emphasis)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, Theme.Space.m)
                    .background(Theme.actionBg)
                    .foregroundStyle(Theme.actionFg)
                    .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))
            }
        }
        .padding(.top, Theme.Space.s)
        .overlay(alignment: .topLeading) {
            if model.remaining > 0 {
                Text("\(model.remaining) left")
                    .font(Theme.Typography.caption)
                    .foregroundStyle(Theme.muted)
                    .offset(y: -Theme.Space.m)
            }
        }
    }

    // MARK: Done

    private var doneView: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Space.l) {
                Text("Session complete")
                    .font(Theme.Typography.title)
                    .foregroundStyle(Theme.text)
                VStack(alignment: .leading, spacing: Theme.Space.s) {
                    summaryRow("Committed", "\(model.attempted)")
                    summaryRow("First-try correct", "\(model.correctCount)")
                    if model.attempted > 0 {
                        summaryRow(
                            "Accuracy",
                            "\(Int((Double(model.correctCount) / Double(model.attempted) * 100).rounded()))%"
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
                Button {
                    dismiss()
                } label: {
                    Text("Done")
                        .font(Theme.Typography.emphasis)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, Theme.Space.m)
                        .background(Theme.actionBg)
                        .foregroundStyle(Theme.actionFg)
                        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))
                }
            }
            .padding(Theme.Space.l)
        }
    }

    private func summaryRow(_ label: String, _ value: String) -> some View {
        HStack {
            Text(label).font(Theme.Typography.body).foregroundStyle(Theme.muted)
            Spacer()
            Text(value).font(Theme.Typography.mono(14)).foregroundStyle(Theme.text)
        }
    }

    // MARK: Shared chrome

    private func centered<Inner: View>(@ViewBuilder _ inner: () -> Inner) -> some View {
        VStack {
            Spacer()
            inner()
            Spacer()
        }
        .padding(Theme.Space.l)
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
