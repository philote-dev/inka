// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Exam mode: a timed, blind, no-help run of the collection's Problems, scored on
// the raw-to-scaled Readiness map (ux-foundation.md §7.2; exam.py). The screen
// assembles a blueprint-weighted run (ExamAssembly), runs a countdown, records
// selections blind (the correct answer is never shown until the end), and on
// finish projects a scaled score with an 80% range (ExamScore), abstaining
// honestly below the coverage gate. The projection reuses the same readiness
// math the desktop uses, so an exam here reads like the desktop's.
//
// On finish, the exam persists one clean Attempt per answered question through
// the write path (AttemptWriter / Engine.logAttempts) and asks Home/Progress to
// recompute, so a phone-run exam feeds Performance/Readiness through the same
// fold as desktop (once a topic crosses its evidence gate). The in-memory result
// is still the sitting's own projection, shown immediately regardless.

import SwiftUI

@MainActor
final class ExamModel: ObservableObject {
    enum Phase: Equatable {
        case config
        case loading
        case empty
        case running
        case finished
        case failed(String)
    }

    @Published private(set) var phase: Phase = .config
    @Published private(set) var problems: [ExamProblem] = []
    @Published var index = 0
    @Published private(set) var selections: [Int64: String] = [:]
    @Published var flags: Set<Int64> = []
    @Published private(set) var remainingSeconds = 0
    @Published private(set) var result: ExamResult?

    private var ticker: Task<Void, Never>?
    // Set at start so finish() can persist attempts on the shared engine and
    // ask Home/Progress to recompute once they land.
    private var engine: Engine?
    private var onPersisted: (() -> Void)?
    // Groups this sitting's attempts (a fresh id per run), for the payload.
    private var sessionId = UUID().uuidString

    var current: ExamProblem? {
        guard problems.indices.contains(index) else { return nil }
        return problems[index]
    }

    var answeredCount: Int { selections.values.filter { !$0.isEmpty }.count }

    func start(engine: Engine, section: Bool, onPersisted: @escaping () -> Void) async {
        self.engine = engine
        self.onPersisted = onPersisted
        self.sessionId = UUID().uuidString
        phase = .loading
        do {
            let bank = try await engine.loadProblems()
            let count = section
                ? ExamAssembly.defaultSectionQuestionCount
                : ExamAssembly.fullLengthQuestionCount
            let assembled = ExamAssembly.assemble(problems: bank, questionCount: count)
            guard !assembled.isEmpty else {
                phase = .empty
                return
            }
            problems = assembled
            index = 0
            selections = [:]
            flags = []
            remainingSeconds = Int((ExamAssembly.secondsPerQuestion * Double(assembled.count)).rounded())
            phase = .running
            runTimer()
        } catch {
            phase = .failed(String(describing: error))
        }
    }

    func select(_ letter: String) {
        guard let current else { return }
        selections[current.noteId] = letter
    }

    func selection(for problem: ExamProblem) -> String? {
        selections[problem.noteId]
    }

    func toggleFlag() {
        guard let current else { return }
        if flags.contains(current.noteId) {
            flags.remove(current.noteId)
        } else {
            flags.insert(current.noteId)
        }
    }

    func goNext() { if index < problems.count - 1 { index += 1 } }
    func goPrevious() { if index > 0 { index -= 1 } }

    func finish() {
        guard phase == .running else { return }
        ticker?.cancel()
        ticker = nil
        let answered: [(category: String, correct: Bool)] = problems.compactMap { problem in
            guard let letter = selections[problem.noteId], !letter.isEmpty else { return nil }
            return (problem.category, letter == problem.correctLetter)
        }
        result = ExamScore.score(answered: answered, served: problems.count)
        phase = .finished
        persistAttempts()
    }

    /// Persist one clean Attempt per answered question (skipped ones are not
    /// attempts), then ask Home/Progress to recompute. Timed, no help, committed
    /// first-try answers, so every attempt is ladder_depth 0 and honest. Failure
    /// to persist never disturbs the on-screen result; the sitting still reports.
    private func persistAttempts() {
        guard let engine else { return }
        let drafts = attemptDrafts()
        guard !drafts.isEmpty else { return }
        Task { @MainActor [weak self] in
            try? await engine.logAttempts(drafts)
            self?.onPersisted?()
        }
    }

    /// One draft per answered question. Exam mode allows revisiting questions, so
    /// per-item think time is not measured; `responseMs` is left off (which the
    /// clean rule treats as clean) rather than inventing a latency.
    private func attemptDrafts() -> [AttemptDraft] {
        let now = Int(Date().timeIntervalSince1970)
        return problems.compactMap { problem in
            guard let letter = selections[problem.noteId], !letter.isEmpty else { return nil }
            return AttemptDraft(
                itemNoteId: problem.noteId,
                topic: problem.topic,
                category: problem.category,
                correct: letter == problem.correctLetter,
                selectedOption: letter,
                sessionId: sessionId,
                answeredAt: now,
                ladderDepth: 0,
                difficulty: problem.difficulty,
                responseMs: nil
            )
        }
    }

    func stop() {
        ticker?.cancel()
        ticker = nil
    }

    private func runTimer() {
        ticker?.cancel()
        ticker = Task { [weak self] in
            while true {
                try? await Task.sleep(nanoseconds: 1_000_000_000)
                guard let self, !Task.isCancelled else { return }
                guard self.remainingSeconds > 0 else { return }
                self.remainingSeconds -= 1
                if self.remainingSeconds == 0 { self.finish() }
            }
        }
    }
}

struct ExamView: View {
    @EnvironmentObject private var app: AppModel
    @Environment(\.dismiss) private var dismiss
    @StateObject private var model = ExamModel()

    var body: some View {
        NavigationStack {
            content
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                .background(Theme.canvas.ignoresSafeArea())
                .navigationTitle("Exam")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button(model.phase == .finished ? "Done" : "Close") {
                            model.stop()
                            dismiss()
                        }
                    }
                }
        }
        .onDisappear { model.stop() }
    }

    @ViewBuilder
    private var content: some View {
        switch model.phase {
        case .config:
            configView
        case .loading:
            centered { ProgressView("Assembling your exam…") }
        case .empty:
            centered {
                statusCard(
                    title: "No problems yet",
                    message: "This collection has no problem bank. Sync from desktop to load problems, then take a timed exam.",
                    tint: Theme.caution
                )
            }
        case .running:
            runningView
        case .finished:
            resultView
        case let .failed(message):
            centered { statusCard(title: "Something went wrong", message: message, tint: Theme.error) }
        }
    }

    // MARK: Config

    private var configView: some View {
        VStack(alignment: .leading, spacing: Theme.Space.l) {
            VStack(alignment: .leading, spacing: Theme.Space.s) {
                Text("Timed exam")
                    .font(Theme.Typography.title)
                    .foregroundStyle(Theme.text)
                Text(ExamNarration.noHelpLine)
                    .font(Theme.Typography.body)
                    .foregroundStyle(Theme.muted)
            }
            examOptionButton(
                title: "Short section",
                subtitle: "\(ExamAssembly.defaultSectionQuestionCount) questions, blueprint-weighted",
                section: true
            )
            examOptionButton(
                title: "Full mock",
                subtitle: "Up to \(ExamAssembly.fullLengthQuestionCount) questions at real PGRE proportions",
                section: false
            )
            Text("Your score projects to the full 200-990 PGRE band with an 80% range, and abstains honestly if too little of the exam is covered.")
                .font(Theme.Typography.caption)
                .foregroundStyle(Theme.muted)
            Spacer()
        }
        .padding(Theme.Space.l)
    }

    private func examOptionButton(title: String, subtitle: String, section: Bool) -> some View {
        Button {
            Task { await model.start(engine: app.engine, section: section, onPersisted: { app.refreshScores() }) }
        } label: {
            VStack(alignment: .leading, spacing: Theme.Space.xs) {
                Text(title)
                    .font(Theme.Typography.emphasis)
                    .foregroundStyle(Theme.text)
                Text(subtitle)
                    .font(Theme.Typography.caption)
                    .foregroundStyle(Theme.muted)
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

    // MARK: Running

    @ViewBuilder
    private var runningView: some View {
        if let problem = model.current {
            VStack(spacing: Theme.Space.l) {
                runningHeader
                ScrollView {
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
                navigationBar
            }
            .padding(Theme.Space.l)
        } else {
            centered { statusCard(title: "No question", message: "The exam is empty.", tint: Theme.caution) }
        }
    }

    private var runningHeader: some View {
        HStack {
            Label(Self.clock(model.remainingSeconds), systemImage: "timer")
                .font(Theme.Typography.mono(15, weight: .semibold))
                .foregroundStyle(model.remainingSeconds < 60 ? Theme.caution : Theme.text)
            Spacer()
            Text("Q\(model.index + 1) of \(model.problems.count)")
                .font(Theme.Typography.caption)
                .foregroundStyle(Theme.muted)
            Button {
                model.toggleFlag()
            } label: {
                Image(systemName: model.current.map { model.flags.contains($0.noteId) } == true
                    ? "flag.fill" : "flag")
                    .foregroundStyle(Theme.text)
            }
        }
    }

    // The shared MCQ list, drawn blind. The exam never reveals the correct answer
    // during the run, so the group stays pre-commit (committed false, no
    // correctKey) and only its selection affordance is used. Selection lives in
    // the model, keyed by note; `problem` is always `model.current` here.
    private func choiceList(_ problem: ExamProblem) -> some View {
        ChoiceListView(
            choices: ChoiceList.lettered(problem.choices),
            selected: Binding(
                get: { model.selection(for: problem) },
                set: { picked in if let picked { model.select(picked) } }
            )
        )
    }

    private var navigationBar: some View {
        HStack(spacing: Theme.Space.s) {
            Button {
                model.goPrevious()
            } label: {
                Text("Previous")
                    .font(Theme.Typography.body)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, Theme.Space.m)
                    .foregroundStyle(Theme.text)
                    .overlay(
                        RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous)
                            .stroke(Theme.border, lineWidth: 1)
                    )
            }
            .disabled(model.index == 0)

            if model.index >= model.problems.count - 1 {
                Button {
                    model.finish()
                } label: {
                    Text("Finish")
                        .font(Theme.Typography.emphasis)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, Theme.Space.m)
                        .background(Theme.actionBg)
                        .foregroundStyle(Theme.actionFg)
                        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))
                }
            } else {
                Button {
                    model.goNext()
                } label: {
                    Text("Next")
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

    // MARK: Result

    @ViewBuilder
    private var resultView: some View {
        if let result = model.result {
            ScrollView {
                VStack(alignment: .leading, spacing: Theme.Space.l) {
                    ScoreCardView(
                        kind: .readiness,
                        value: result.scoreValue,
                        updated: nil,
                        scale: .scaled,
                        howSureDetail: result.howSureDetail
                    )
                    resultSummary(result)
                    if !result.byTopic.isEmpty {
                        topicBreakdown(result)
                    }
                    Button {
                        model.stop()
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
        } else {
            centered { statusCard(title: "No result", message: "The exam produced no result.", tint: Theme.caution) }
        }
    }

    private func resultSummary(_ result: ExamResult) -> some View {
        VStack(alignment: .leading, spacing: Theme.Space.s) {
            Text("This sitting")
                .font(Theme.Typography.emphasis)
                .foregroundStyle(Theme.text)
            summaryRow("Answered", "\(result.nAnswered) of \(result.total)")
            summaryRow("Correct", "\(result.correct)")
            summaryRow("Incorrect", "\(result.incorrect)")
            summaryRow("Skipped", "\(result.skipped)")
            summaryRow("Accuracy", "\(Int((result.accuracy * 100).rounded()))%")
            summaryRow("Raw (this sitting)", "\(result.rawActual)")
            if result.abstain {
                Text(result.reason ?? "Projection abstains: not enough of the exam covered.")
                    .font(Theme.Typography.caption)
                    .foregroundStyle(Theme.muted)
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

    private func topicBreakdown(_ result: ExamResult) -> some View {
        VStack(alignment: .leading, spacing: Theme.Space.s) {
            Text("By topic")
                .font(Theme.Typography.emphasis)
                .foregroundStyle(Theme.text)
            ForEach(result.byTopic) { topic in
                HStack {
                    Text(CategoryLabels.label(topic.category))
                        .font(Theme.Typography.body)
                        .foregroundStyle(Theme.text)
                    Spacer()
                    if topic.tested {
                        Text("\(topic.correct)/\(topic.nExam)")
                            .font(Theme.Typography.mono(13))
                            .foregroundStyle(Theme.muted)
                    } else {
                        Text("Not tested")
                            .font(Theme.Typography.caption)
                            .foregroundStyle(Theme.muted)
                    }
                }
                .padding(.vertical, Theme.Space.xs)
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

    /// mm:ss for the countdown.
    static func clock(_ seconds: Int) -> String {
        let m = seconds / 60
        let s = seconds % 60
        return String(format: "%d:%02d", m, s)
    }
}

/// Copy shown on the exam surface (exam.NO_HELP_LINE).
enum ExamNarration {
    static let noHelpLine = "No hints. No help. Timed like the exam."
}

extension ExamResult {
    /// The readiness score-card payload for the exam's projection (scaled band),
    /// or an honest abstain naming why.
    var scoreValue: ScoreValue {
        guard !abstain, let scaled else {
            return .abstaining(reason ?? "Not enough of the exam is covered yet")
        }
        return ScoreValue(
            point: Double(scaled),
            low: low.map(Double.init),
            high: high.map(Double.init),
            abstain: false,
            reason: nil
        )
    }

    var howSureDetail: String? {
        guard !abstain else { return nil }
        return "\(Int((coveragePct * 100).rounded())) percent covered"
    }
}
