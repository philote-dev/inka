// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// The on-device Diagnostic placement flow, a native port of
// ts/routes/pgrep/diagnostic/+page.svelte. A light, re-runnable flow: step
// through the blueprint topics a few at a time, answer one objective quick check
// each (never a self-rating), then place every topic strong or rusty. Placement
// combines the fresh quick check with the FSRS-R Memory prior (Diagnostic.place
// / Engine.placeDiagnostic), and the snapshot persists to the collection config
// under the same key the desktop uses, so it syncs and the completion gate
// matches.
//
// The quick-check step draws the shared ChoiceListView with committed=false and
// no revealed key, so answers are withheld until the whole set commits (the "See
// placement" button) and no choice ever reads red, per the pgrep honesty rule.
// The results screen shows each topic's placement as a strong/rusty chip and,
// best-effort, the freshly-read knowledge terrain (ManifoldWebView). The richer
// diagnostic-overlay manifold is a separate task; this flow just persists the
// placement for it to consume.
//
// Presented as a sheet from RootView (app.isPresentingDiagnostic): auto-offered
// on first run, and reachable from the Home / Progress CTAs and the Settings
// re-run.

import SwiftUI

@MainActor
final class DiagnosticModel: ObservableObject {
    enum Screen: Equatable {
        case loading
        case error
        case intro
        case check
        case results
    }

    @Published private(set) var screen: Screen = .loading
    @Published private(set) var topics: [DiagnosticTopic] = []
    /// category -> selected 0-based choice index for the current pass.
    @Published var answers: [String: Int] = [:]
    @Published var stepIndex = 0
    @Published private(set) var placed: [PlacedTopic] = []
    @Published private(set) var resultSurface: ManifoldSurface?
    @Published private(set) var busy = false

    /// A few topics per step, so the flow steps through rather than showing all at
    /// once (mirrors the Svelte BATCH_SIZE).
    static let batchSize = 3

    /// The quick checks flattened with their category, in blueprint order.
    var checks: [DiagnosticCheckItem] { Diagnostic.checkItems(topics) }

    /// The checks grouped into steps of `batchSize`.
    var batches: [[DiagnosticCheckItem]] {
        let all = checks
        var out: [[DiagnosticCheckItem]] = []
        var index = 0
        while index < all.count {
            out.append(Array(all[index..<min(index + Self.batchSize, all.count)]))
            index += Self.batchSize
        }
        return out
    }

    /// Any topics carrying a placement from a previous run, as placement chips.
    var priorPlacements: [PlacedTopic] {
        topics.compactMap { topic in
            topic.placement.map { PlacedTopic(category: topic.category, placement: $0) }
        }
    }

    var currentBatch: [DiagnosticCheckItem] {
        stepIndex >= 0 && stepIndex < batches.count ? batches[stepIndex] : []
    }

    var batchComplete: Bool { currentBatch.allSatisfy { answers[$0.category] != nil } }
    var isLastStep: Bool { stepIndex >= batches.count - 1 }
    var strongCount: Int { placed.filter { $0.placement == .strong }.count }

    func load(engine: Engine) async {
        screen = .loading
        do {
            topics = try await engine.diagnosticTopics()
            screen = .intro
        } catch {
            screen = .error
        }
    }

    func start() {
        answers = [:]
        stepIndex = 0
        placed = []
        resultSurface = nil
        screen = .check
    }

    func back() {
        if stepIndex > 0 {
            stepIndex -= 1
        } else {
            screen = .intro
        }
    }

    func next() {
        if stepIndex < batches.count - 1 {
            stepIndex += 1
        }
    }

    /// Commit the pass: persist the placement and move to the results screen.
    /// Returns true on success so the caller flips the app-level completion gate.
    func submit(engine: Engine) async -> Bool {
        guard !busy else { return false }
        busy = true
        defer { busy = false }
        do {
            placed = try await engine.placeDiagnostic(answers: answers)
            // Best-effort, like desktop reads pgrepManifold after placing: show the
            // freshly-read knowledge terrain. The chips below stand on their own if
            // this read fails.
            resultSurface = (try? await engine.computeMemory()).map(ManifoldSurface.build(memory:))
            screen = .results
            return true
        } catch {
            screen = .error
            return false
        }
    }
}

struct DiagnosticView: View {
    @EnvironmentObject private var app: AppModel
    @Environment(\.colorScheme) private var colorScheme
    @StateObject private var model = DiagnosticModel()

    var body: some View {
        VStack(spacing: 0) {
            header
            ScrollView {
                VStack(alignment: .leading, spacing: Theme.Space.l) {
                    screenContent
                }
                .padding(.horizontal, Theme.Space.l)
                .padding(.bottom, Theme.Space.xl)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .background(Theme.canvas.ignoresSafeArea())
        .task { await model.load(engine: app.engine) }
    }

    private func close() { app.isPresentingDiagnostic = false }

    // MARK: Header

    private var header: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: Theme.Space.xs) {
                Text("Diagnostic")
                    .font(Theme.Typography.title)
                    .foregroundStyle(Theme.text)
                Text("Place each topic strong or rusty.")
                    .font(Theme.Typography.body)
                    .foregroundStyle(Theme.muted)
            }
            Spacer()
            Button(action: close) {
                Image(systemName: "xmark")
                    .font(Theme.Typography.emphasis)
                    .foregroundStyle(Theme.muted)
                    .padding(Theme.Space.s)
                    .contentShape(Rectangle())
            }
            .accessibilityLabel("Close diagnostic")
        }
        .padding(Theme.Space.l)
    }

    // MARK: Screens

    @ViewBuilder
    private var screenContent: some View {
        switch model.screen {
        case .loading:
            ProgressView("Loading the diagnostic\u{2026}")
                .frame(maxWidth: .infinity, minHeight: 200)
        case .error:
            panel {
                Text("Something went wrong.")
                    .font(Theme.Typography.emphasis)
                    .foregroundStyle(Theme.text)
                Button("Try again") { Task { await model.load(engine: app.engine) } }
                    .buttonStyle(.bordered)
                    .tint(Theme.text)
            }
        case .intro:
            introScreen
        case .check:
            checkScreen
        case .results:
            resultsScreen
        }
    }

    private var introScreen: some View {
        VStack(alignment: .leading, spacing: Theme.Space.l) {
            panel {
                Text("Answer one quick check per topic.")
                    .font(Theme.Typography.emphasis)
                    .foregroundStyle(Theme.text)
                Text("We combine each answer with what your reviews already show, then place every topic strong or rusty. Run it again whenever you like.")
                    .font(Theme.Typography.body)
                    .foregroundStyle(Theme.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if !model.priorPlacements.isEmpty {
                VStack(alignment: .leading, spacing: Theme.Space.s) {
                    Text("Your last placement")
                        .font(Theme.Typography.caption)
                        .foregroundStyle(Theme.muted)
                    chipGrid(model.priorPlacements)
                }
            }

            VStack(spacing: Theme.Space.m) {
                primaryButton(model.priorPlacements.isEmpty ? "Start" : "Run again", enabled: true) {
                    model.start()
                }
                Button("Maybe later", action: close)
                    .font(Theme.Typography.body)
                    .foregroundStyle(Theme.muted)
            }
        }
    }

    private var checkScreen: some View {
        VStack(alignment: .leading, spacing: Theme.Space.l) {
            Text("Step \(model.stepIndex + 1) of \(model.batches.count)")
                .font(Theme.Typography.caption)
                .foregroundStyle(Theme.muted)

            ForEach(model.currentBatch) { item in
                questionCard(item)
            }

            HStack(spacing: Theme.Space.m) {
                Button("Back") { model.back() }
                    .buttonStyle(.bordered)
                    .tint(Theme.text)
                    .disabled(model.busy)
                if model.isLastStep {
                    primaryButton(model.busy ? "Placing\u{2026}" : "See placement",
                                  enabled: model.batchComplete && !model.busy) {
                        Task {
                            if await model.submit(engine: app.engine) {
                                app.markDiagnosticComplete()
                            }
                        }
                    }
                } else {
                    primaryButton("Next", enabled: model.batchComplete) { model.next() }
                }
            }

            Text("Pick an answer for each check to continue.")
                .font(Theme.Typography.caption)
                .foregroundStyle(Theme.muted)
        }
    }

    private var resultsScreen: some View {
        VStack(alignment: .leading, spacing: Theme.Space.l) {
            panel {
                Text("\(model.strongCount) of \(model.placed.count) topics placed strong.")
                    .font(Theme.Typography.emphasis)
                    .foregroundStyle(Theme.text)
                Text("Saved. Reviews keep refining this, and you can run it again.")
                    .font(Theme.Typography.caption)
                    .foregroundStyle(Theme.muted)
            }

            if let surface = model.resultSurface {
                ManifoldWebView(surface: surface, colorScheme: colorScheme)
                    .frame(height: 200)
            }

            chipGrid(model.placed)
            legend
            primaryButton("Done", enabled: true, action: close)
        }
    }

    // MARK: Pieces

    private func questionCard(_ item: DiagnosticCheckItem) -> some View {
        VStack(alignment: .leading, spacing: Theme.Space.m) {
            Text(CategoryLabels.label(item.category))
                .font(Theme.Typography.caption)
                .textCase(.uppercase)
                .foregroundStyle(Theme.muted)
            MathText(html: item.prompt, fontSize: 17)
                .frame(maxWidth: .infinity, alignment: .leading)
            ChoiceListView(
                choices: ChoiceList.lettered(item.choices),
                selected: selection(for: item),
                committed: false,
                correctKey: nil
            )
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

    private func chipGrid(_ items: [PlacedTopic]) -> some View {
        LazyVGrid(
            columns: [GridItem(.adaptive(minimum: 150), spacing: Theme.Space.s)],
            alignment: .leading,
            spacing: Theme.Space.s
        ) {
            ForEach(items) { chip($0) }
        }
    }

    private func chip(_ item: PlacedTopic) -> some View {
        let strong = item.placement == .strong
        let accent = strong ? Theme.success : Theme.caution
        return HStack(spacing: Theme.Space.s) {
            Text(CategoryLabels.label(item.category))
                .font(Theme.Typography.body)
                .foregroundStyle(Theme.text)
                .lineLimit(1)
                .truncationMode(.tail)
            Spacer(minLength: Theme.Space.s)
            Text(item.placement.rawValue)
                .font(Theme.Typography.caption)
                .textCase(.uppercase)
                .foregroundStyle(accent)
        }
        .padding(.horizontal, Theme.Space.m)
        .padding(.vertical, Theme.Space.s + Theme.Space.xs)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.surface)
        .overlay(alignment: .leading) {
            Rectangle().fill(accent).frame(width: 3)
        }
        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.row, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: Theme.Radius.row, style: .continuous)
                .stroke(Theme.border, lineWidth: 1)
        )
    }

    private var legend: some View {
        HStack(spacing: Theme.Space.l) {
            legendKey(color: Theme.success, label: "strong")
            legendKey(color: Theme.caution, label: "rusty, needs work")
        }
        .accessibilityHidden(true)
    }

    private func legendKey(color: Color, label: String) -> some View {
        HStack(spacing: Theme.Space.xs) {
            RoundedRectangle(cornerRadius: 3).fill(color).frame(width: 12, height: 12)
            Text(label)
                .font(Theme.Typography.small)
                .foregroundStyle(Theme.muted)
        }
    }

    private func panel<Content: View>(@ViewBuilder _ content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: Theme.Space.s) {
            content()
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

    private func primaryButton(_ title: String, enabled: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(Theme.Typography.emphasis)
                .frame(maxWidth: .infinity)
                .padding(.vertical, Theme.Space.m)
                .background(Theme.actionBg)
                .foregroundStyle(Theme.actionFg)
                .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))
                .opacity(enabled ? 1 : 0.5)
        }
        .disabled(!enabled)
    }

    // MARK: Selection binding

    /// A two-way binding between the shared ChoiceListView (letter keys) and the
    /// stored answer (0-based index). The letter maps back through the same
    /// ChoiceList.letter labeling the list draws with, so A..E round-trips.
    private func selection(for item: DiagnosticCheckItem) -> Binding<String?> {
        Binding(
            get: { model.answers[item.category].map { ChoiceList.letter(for: $0) } },
            set: { key in
                guard let key,
                      let index = (0..<item.choices.count).first(where: { ChoiceList.letter(for: $0) == key })
                else { return }
                model.answers[item.category] = index
            }
        )
    }
}

/// A quiet monochrome entry into the re-runnable Diagnostic, shown on Home and
/// Progress until it has been completed once (mirrors the desktop diag-link). It
/// seeds the per-topic placement the manifold and Progress read.
struct DiagnosticCTA: View {
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: Theme.Space.s) {
                Image(systemName: "chart.xyaxis.line")
                    .font(Theme.Typography.body)
                Text("Run the diagnostic")
                    .font(Theme.Typography.body)
                Spacer()
                Image(systemName: "chevron.right")
                    .font(Theme.Typography.caption)
            }
            .foregroundStyle(Theme.muted)
            .padding(.horizontal, Theme.Space.m)
            .padding(.vertical, Theme.Space.s + Theme.Space.xs)
            .frame(maxWidth: .infinity, alignment: .leading)
            .overlay(
                RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous)
                    .stroke(Theme.border, lineWidth: 1)
            )
        }
        .accessibilityLabel("Run the diagnostic")
    }
}
