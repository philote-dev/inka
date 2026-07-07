// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Library: the Card Sets browser (design_handoff_card_sets, ts/routes/pgrep/
// library + CardWheel.svelte). AI is off on the phone, so this is the Card Sets
// surface, plus the voluntary calibration walkthrough (never a wall).
//
// A native SwiftUI analog of the web "wheel", not a reproduction of its FLIP/3D
// animation: a horizontal one-up carousel selects a category set (mirroring the
// wheel's phone one-up mode), and the selected set's cards read below as a
// scroll of flip cards (tap to reveal the back), typeset with the shared
// MathText. "Add a card" authors the learner's own front/back as-is into the
// set (no AI) via Engine.addCard, then reloads so the new card lands in its set
// and the counts update, exactly like the desktop composer.
//
// Because AI is off, calibration is voluntary and never gates Study. Mirroring
// the desktop AI-off Library, an uncalibrated collection shows a dismissible
// "Teach pgrep your style" strip that launches the walkthrough: author one card
// per blueprint category (the generation-effect act), with no stylize/gap-fill.
// Progress and the honest completion state read the calibration status; the
// strip clears once every category has a learner-authored card.

import SwiftUI

@MainActor
final class LibraryModel: ObservableObject {
    enum LoadState: Equatable {
        case loading
        case loaded([CardSet])
        case failed(String)
    }

    @Published private(set) var state: LoadState = .loading
    /// The centered set's category (drives the carousel and the cards below).
    @Published var selectedCategory: String = ""
    /// The calibration gate status ({calibrated, authored, required}), read
    /// alongside the sets so the Library can show the voluntary walkthrough entry
    /// and its progress. Secondary to the sets: a hiccup leaves it nil (the entry
    /// simply stays hidden), never failing the surface. AI is off, so this only
    /// ever drives the voluntary entry, never a gate.
    @Published var calibration: CalibrationStatus?

    var sets: [CardSet] {
        if case let .loaded(sets) = state { return sets }
        return []
    }

    /// The currently centered set (falls back to the first while the selection
    /// settles), or nil when there are no sets.
    var selectedSet: CardSet? {
        sets.first { $0.category == selectedCategory } ?? sets.first
    }

    /// Read the card sets. The first load shows a spinner; later reloads (after a
    /// sync, a reset, or an add) swap the sets in place without a loading flash,
    /// and keep the current selection when that category still exists.
    func load(engine: Engine) async {
        do {
            let loaded = try await engine.loadCardSets()
            state = .loaded(loaded)
            reconcileSelection(loaded)
        } catch {
            state = .failed(String(describing: error))
        }
        await reloadCalibration(engine: engine)
    }

    /// Re-read the calibration status (best-effort). Called on load and after the
    /// walkthrough authors cards, so the voluntary entry clears once every
    /// blueprint category has a learner-authored card.
    func reloadCalibration(engine: Engine) async {
        calibration = try? await engine.calibrationStatus()
    }

    /// Author one card, then reload so it appears in its set and the counts
    /// update. The set it landed in is centered. Returns true on success, so the
    /// composer sheet can close only when the write actually persisted.
    func add(engine: Engine, category: String, front: String, back: String) async -> Bool {
        do {
            _ = try await engine.addCard(category: category, front: front, back: back)
            let loaded = try await engine.loadCardSets()
            state = .loaded(loaded)
            selectedCategory = category
            return true
        } catch {
            return false
        }
    }

    /// Keep the centered category pointing at a set that still exists, defaulting
    /// to the first (blueprint-order) set.
    private func reconcileSelection(_ sets: [CardSet]) {
        if !sets.contains(where: { $0.category == selectedCategory }) {
            selectedCategory = sets.first?.category ?? ""
        }
    }
}

struct LibraryView: View {
    @EnvironmentObject private var app: AppModel
    @StateObject private var model = LibraryModel()
    @State private var isAdding = false
    @State private var isWalkthrough = false
    /// The voluntary calibration entry is dismissible for the session, mirroring
    /// the desktop's entryDismissed. AI is off, so it is never a wall.
    @State private var entryDismissed = false

    /// Whether to offer the voluntary "Teach pgrep your style" walkthrough: the
    /// collection is not yet calibrated and the strip has not been dismissed.
    /// Mirrors the desktop showTeachEntry with AI off (so no aiEnabled term).
    private var showTeachEntry: Bool {
        if let calibration = model.calibration {
            return !calibration.calibrated && !entryDismissed
        }
        return false
    }

    var body: some View {
        NavigationStack {
            content
                .background(Theme.canvas.ignoresSafeArea())
                .navigationTitle("Card Sets")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .navigationBarTrailing) {
                        Button { isAdding = true } label: {
                            Image(systemName: "plus")
                        }
                        .tint(Theme.text)
                        .accessibilityLabel("Add a card")
                    }
                }
        }
        .task(id: app.dataVersion) { await model.load(engine: app.engine) }
        .sheet(isPresented: $isAdding) {
            AddCardSheet(defaultCategory: model.selectedCategory) { category, front, back in
                await model.add(engine: app.engine, category: category, front: front, back: back)
            }
        }
        .sheet(isPresented: $isWalkthrough, onDismiss: {
            // Re-read the sets and calibration on any dismissal (Done or swipe),
            // so the newly authored cards land in their sets and the entry clears
            // once every category is covered.
            Task { await model.load(engine: app.engine) }
        }) {
            CalibrationWalkthroughView()
                .environmentObject(app)
        }
    }

    @ViewBuilder
    private var content: some View {
        switch model.state {
        case .loading:
            centered { ProgressView("Reading your sets\u{2026}") }
        case let .failed(message):
            centered {
                VStack(spacing: Theme.Space.s) {
                    Image(systemName: "exclamationmark.triangle")
                        .font(.system(size: 32))
                        .foregroundStyle(Theme.error)
                    Text("Could not load your library.")
                        .font(Theme.Typography.emphasis)
                        .foregroundStyle(Theme.text)
                    Text(message)
                        .font(Theme.Typography.caption)
                        .foregroundStyle(Theme.muted)
                        .multilineTextAlignment(.center)
                }
                .padding(Theme.Space.xl)
            }
        case let .loaded(sets):
            if sets.isEmpty {
                emptyState
            } else {
                loaded(sets)
            }
        }
    }

    private func loaded(_ sets: [CardSet]) -> some View {
        VStack(spacing: 0) {
            if showTeachEntry {
                teachEntry
            }
            summary(sets)
            carousel(sets)
                .frame(height: 210)
            Divider().background(Theme.border)
            cardsList
        }
    }

    /// The voluntary calibration entry: a calm strip, never a wall. "Start" opens
    /// the walkthrough; the close button dismisses it for the session. Mirrors the
    /// desktop teach-entry (AI off, uncalibrated), including the authored/required
    /// progress so the learner sees how far along they are.
    private var teachEntry: some View {
        HStack(alignment: .top, spacing: Theme.Space.m) {
            VStack(alignment: .leading, spacing: 2) {
                Text("Teach pgrep your style")
                    .font(Theme.Typography.emphasis)
                    .foregroundStyle(Theme.text)
                Text("Write one card per topic in your own words. It is the fastest way to make this stick.")
                    .font(Theme.Typography.caption)
                    .foregroundStyle(Theme.muted)
                    .fixedSize(horizontal: false, vertical: true)
                if let calibration = model.calibration {
                    Text("\(calibration.authored) of \(calibration.required) topics")
                        .font(Theme.Typography.mono(11))
                        .foregroundStyle(Theme.muted)
                }
            }
            Spacer(minLength: 0)
            VStack(spacing: Theme.Space.s) {
                Button { isWalkthrough = true } label: {
                    Text("Start")
                        .font(Theme.Typography.body)
                        .padding(.vertical, Theme.Space.s)
                        .padding(.horizontal, Theme.Space.m)
                        .background(Theme.actionBg)
                        .foregroundStyle(Theme.actionFg)
                        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))
                }
                .buttonStyle(.plain)
                Button { entryDismissed = true } label: {
                    Image(systemName: "xmark")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(Theme.muted)
                        .frame(width: 28, height: 28)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Dismiss")
            }
        }
        .padding(Theme.Space.m)
        .background(Theme.surface)
        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous)
                .stroke(Theme.border, lineWidth: 1)
        )
        .padding(.horizontal, Theme.Space.l)
        .padding(.top, Theme.Space.m)
    }

    private func summary(_ sets: [CardSet]) -> some View {
        let total = sets.reduce(0) { $0 + $1.cards.count }
        return Text("\(sets.count) \(sets.count == 1 ? "topic" : "topics"), \(total) \(total == 1 ? "card" : "cards")")
            .font(Theme.Typography.caption)
            .foregroundStyle(Theme.muted)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, Theme.Space.l)
            .padding(.top, Theme.Space.s)
    }

    private func carousel(_ sets: [CardSet]) -> some View {
        TabView(selection: $model.selectedCategory) {
            ForEach(sets) { set in
                setDeck(set).tag(set.category)
            }
        }
        .tabViewStyle(.page(indexDisplayMode: .always))
        .indexViewStyle(.page(backgroundDisplayMode: .interactive))
    }

    /// One category's "deck": its name, a real deck-face preview (the first
    /// card's front), and the real card count. The centered set in the carousel.
    private func setDeck(_ set: CardSet) -> some View {
        VStack(alignment: .leading, spacing: Theme.Space.s) {
            Text(set.name.uppercased())
                .font(Theme.Typography.caption)
                .tracking(1.2)
                .foregroundStyle(Theme.muted)
            Group {
                if let first = set.cards.first {
                    MathText(html: first.front, fontSize: 16)
                        .frame(maxWidth: .infinity, alignment: .leading)
                } else {
                    Text("No cards yet")
                        .font(Theme.Typography.body)
                        .foregroundStyle(Theme.muted)
                }
            }
            .frame(maxHeight: 80, alignment: .top)
            .clipped()
            Spacer(minLength: 0)
            Text("\(set.cards.count) \(set.cards.count == 1 ? "card" : "cards")")
                .font(Theme.Typography.mono(13))
                .foregroundStyle(Theme.muted)
        }
        .padding(Theme.Space.l)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        .background(Theme.surface)
        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous)
                .stroke(Theme.border, lineWidth: 1)
        )
        .padding(.horizontal, Theme.Space.l)
        .padding(.bottom, Theme.Space.l)
    }

    private var cardsList: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: Theme.Space.m) {
                if let set = model.selectedSet {
                    Text("Cards in \(set.name)")
                        .font(Theme.Typography.caption)
                        .foregroundStyle(Theme.muted)
                    if set.cards.isEmpty {
                        // Defensive: the read model omits empty categories, so this
                        // is only reached for a set emptied out from under us. Honest,
                        // never a broken list.
                        Text("No cards in this set yet. Add one to get started.")
                            .font(Theme.Typography.body)
                            .foregroundStyle(Theme.muted)
                            .padding(.vertical, Theme.Space.m)
                    } else {
                        ForEach(set.cards) { card in
                            FlipCard(card: card)
                        }
                    }
                    AddCardTile { isAdding = true }
                }
            }
            .padding(Theme.Space.l)
        }
    }

    private var emptyState: some View {
        centered {
            VStack(spacing: Theme.Space.m) {
                Text("Your sets")
                    .font(Theme.Typography.title)
                    .foregroundStyle(Theme.text)
                Text("No card sets yet. Sync your seeded content, or author a card, and your topics will appear here to browse.")
                    .font(Theme.Typography.body)
                    .foregroundStyle(Theme.muted)
                    .multilineTextAlignment(.center)
                Button { isAdding = true } label: {
                    Text("Add a card")
                        .font(Theme.Typography.emphasis)
                        .padding(.vertical, Theme.Space.s + Theme.Space.xs)
                        .padding(.horizontal, Theme.Space.xl)
                        .background(Theme.actionBg)
                        .foregroundStyle(Theme.actionFg)
                        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))
                }
            }
            .frame(maxWidth: 360)
            .padding(Theme.Space.xl)
        }
    }

    private func centered<Inner: View>(@ViewBuilder _ inner: () -> Inner) -> some View {
        VStack { inner() }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

/// One card in the open set: front shown, tap to reveal the back. Both faces are
/// typeset with the shared MathText (which disables its own hit testing, so the
/// tap lands on the card).
private struct FlipCard: View {
    let card: CardSetCard
    @State private var showBack = false

    var body: some View {
        Button {
            withAnimation(Theme.Motion.spring) { showBack.toggle() }
        } label: {
            VStack(alignment: .leading, spacing: Theme.Space.s) {
                MathText(html: card.front, fontSize: 16)
                    .frame(maxWidth: .infinity, alignment: .leading)
                if showBack {
                    Divider().background(Theme.border)
                    MathText(html: card.back, fontSize: 15)
                        .frame(maxWidth: .infinity, alignment: .leading)
                } else {
                    Text("Tap to flip")
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
        .buttonStyle(.plain)
    }
}

/// The in-context "Add a card" affordance at the end of a set (a dashed tile,
/// mirroring the web add tile). Opens the composer with the open set preselected.
private struct AddCardTile: View {
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: Theme.Space.s) {
                Image(systemName: "plus")
                Text("Add a card")
            }
            .font(Theme.Typography.body)
            .foregroundStyle(Theme.muted)
            .frame(maxWidth: .infinity)
            .padding(.vertical, Theme.Space.l)
            .overlay(
                RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous)
                    .stroke(style: StrokeStyle(lineWidth: 1, dash: [5, 4]))
                    .foregroundStyle(Theme.border)
            )
        }
        .buttonStyle(.plain)
    }
}

/// The "Add a card" composer: category, front, back. Authors the learner's own
/// front/back as-is (no AI). Empty front does not submit (matching the web
/// composer); the sheet closes only when the write persisted.
private struct AddCardSheet: View {
    let defaultCategory: String
    let onAdd: (String, String, String) async -> Bool

    @Environment(\.dismiss) private var dismiss
    @State private var category: String
    @State private var front = ""
    @State private var back = ""
    @State private var busy = false

    init(defaultCategory: String, onAdd: @escaping (String, String, String) async -> Bool) {
        self.defaultCategory = defaultCategory
        self.onAdd = onAdd
        let initial = Blueprint.byCategory[defaultCategory] != nil
            ? defaultCategory
            : (Blueprint.slugs.first ?? "mechanics")
        _category = State(initialValue: initial)
    }

    private var canSubmit: Bool {
        !front.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !busy
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Topic") {
                    Picker("Category", selection: $category) {
                        ForEach(Blueprint.slugs, id: \.self) { slug in
                            Text(CardSets.displayName(for: slug)).tag(slug)
                        }
                    }
                }
                Section("Front") {
                    TextField("Write it in your own words.", text: $front, axis: .vertical)
                        .lineLimit(2 ... 6)
                }
                Section("Back") {
                    TextField("The answer, stated plainly.", text: $back, axis: .vertical)
                        .lineLimit(1 ... 6)
                }
            }
            .scrollContentBackground(.hidden)
            .background(Theme.canvas.ignoresSafeArea())
            .navigationTitle("Add a card")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }.tint(Theme.text)
                }
                ToolbarItem(placement: .confirmationAction) {
                    if busy {
                        ProgressView()
                    } else {
                        Button("Add") { submit() }
                            .tint(Theme.text)
                            .disabled(!canSubmit)
                    }
                }
            }
        }
    }

    private func submit() {
        guard canSubmit else { return }
        busy = true
        Task {
            let ok = await onAdd(category, front, back)
            busy = false
            if ok { dismiss() }
        }
    }
}

/// The voluntary "Teach pgrep your style" calibration walkthrough (AI off): step
/// through the blueprint one topic at a time and author one card each, the
/// generation-effect act. A native analog of the desktop Walkthrough.svelte's
/// AI-off path (author only, no stylize or gap-fill). Progress and the honest
/// completion state read the calibration status (authored / required), so
/// authoring the last category's card calibrates the collection durably. It never
/// gates Study; the learner can close it at any point, and authored cards are the
/// same seed notes CardSets.addCard writes (so they merge on sync).
private struct CalibrationWalkthroughView: View {
    @EnvironmentObject private var app: AppModel
    @Environment(\.dismiss) private var dismiss

    @State private var topicIndex = 0
    @State private var front = ""
    @State private var back = ""
    @State private var busy = false
    @State private var error: String?
    @State private var status: CalibrationStatus?

    /// The blueprint categories, in blueprint order. One card per category, so
    /// the walk and the calibration gate line up exactly.
    private let slugs = Blueprint.slugs

    private var slug: String { slugs[min(topicIndex, slugs.count - 1)] }
    private var total: Int { slugs.count }
    private var authored: Int { status?.authored ?? 0 }
    private var calibrated: Bool { status?.calibrated ?? false }

    /// Both faces are required, matching the desktop walkthrough (author needs a
    /// front and a back), stricter than the wheel's "Add a card" (front only).
    private var canSubmit: Bool {
        !front.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !back.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !busy
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: Theme.Space.l) {
                    progressHeader
                    if calibrated {
                        completion
                    } else {
                        editor
                    }
                }
                .padding(Theme.Space.l)
            }
            .background(Theme.canvas.ignoresSafeArea())
            .navigationTitle("Teach pgrep your style")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }.tint(Theme.text)
                }
            }
        }
        .task { await refreshStatus() }
    }

    // MARK: Sections

    private var progressHeader: some View {
        VStack(alignment: .leading, spacing: Theme.Space.s) {
            Text("\(authored) of \(total) topics authored")
                .font(Theme.Typography.emphasis)
                .foregroundStyle(Theme.text)
            ProgressView(value: Double(min(authored, total)), total: Double(total))
                .tint(Theme.memoryText)
            Text("Write one card per topic in your own words. No AI, just you.")
                .font(Theme.Typography.caption)
                .foregroundStyle(Theme.muted)
        }
    }

    private var editor: some View {
        VStack(alignment: .leading, spacing: Theme.Space.m) {
            HStack {
                Text("Card \(topicIndex + 1) of \(total)")
                    .font(Theme.Typography.caption)
                    .foregroundStyle(Theme.muted)
                Spacer()
                HStack(spacing: Theme.Space.l) {
                    Button { step(-1) } label: { Image(systemName: "chevron.left") }
                        .disabled(topicIndex == 0)
                    Button { step(1) } label: { Image(systemName: "chevron.right") }
                        .disabled(topicIndex == total - 1)
                }
                .tint(Theme.text)
            }

            Text(CardSets.displayName(for: slug))
                .font(Theme.Typography.title)
                .foregroundStyle(Theme.memoryText)

            field(title: "FRONT", text: $front, placeholder: "What does this concept test?", lines: 2 ... 4)
            field(title: "BACK", text: $back, placeholder: "Your concise answer, in your own words.", lines: 3 ... 6)

            if let error {
                Text(error)
                    .font(Theme.Typography.caption)
                    .foregroundStyle(Theme.caution)
            }

            Button { submit() } label: {
                HStack(spacing: Theme.Space.s) {
                    if busy { ProgressView().tint(Theme.actionFg) }
                    Text(busy ? "Adding" : "Add this card")
                        .font(Theme.Typography.emphasis)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, Theme.Space.s + Theme.Space.xs)
                .background(Theme.actionBg.opacity(canSubmit ? 1 : 0.5))
                .foregroundStyle(Theme.actionFg)
                .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))
            }
            .buttonStyle(.plain)
            .disabled(!canSubmit)

            Text("AI is off, so no cards are drafted for you. Write each one yourself, or close this any time.")
                .font(Theme.Typography.caption)
                .foregroundStyle(Theme.muted)
        }
    }

    private var completion: some View {
        VStack(alignment: .leading, spacing: Theme.Space.m) {
            Text("You taught pgrep your style")
                .font(Theme.Typography.title)
                .foregroundStyle(Theme.text)
            Text("Every blueprint topic has a card in your own words. Calibration stays complete even if you edit or remove cards later.")
                .font(Theme.Typography.body)
                .foregroundStyle(Theme.muted)
            Button { dismiss() } label: {
                Text("Done")
                    .font(Theme.Typography.emphasis)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, Theme.Space.s + Theme.Space.xs)
                    .background(Theme.actionBg)
                    .foregroundStyle(Theme.actionFg)
                    .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))
            }
            .buttonStyle(.plain)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func field(title: String, text: Binding<String>, placeholder: String, lines: ClosedRange<Int>) -> some View {
        VStack(alignment: .leading, spacing: Theme.Space.xs) {
            Text(title)
                .font(Theme.Typography.caption)
                .tracking(1.2)
                .foregroundStyle(Theme.muted)
            TextField(placeholder, text: text, axis: .vertical)
                .lineLimit(lines)
                .font(Theme.Typography.body)
                .padding(Theme.Space.m)
                .background(Theme.elevated)
                .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous)
                        .stroke(Theme.border, lineWidth: 1)
                )
        }
    }

    // MARK: Actions

    private func refreshStatus() async {
        status = try? await app.engine.calibrationStatus()
    }

    private func step(_ delta: Int) {
        let next = topicIndex + delta
        guard next >= 0, next < total else { return }
        topicIndex = next
        front = ""
        back = ""
        error = nil
    }

    private func submit() {
        guard canSubmit else {
            error = "Write both the front and the back first."
            return
        }
        busy = true
        error = nil
        Task {
            do {
                _ = try await app.engine.addCard(category: slug, front: front, back: back)
                await refreshStatus()
                // Guide onward: advance to the next topic and clear the editor,
                // exactly like the desktop walkthrough after a card lands.
                if topicIndex < total - 1 { topicIndex += 1 }
                front = ""
                back = ""
            } catch {
                self.error = "Could not add this card. Try again."
            }
            busy = false
        }
    }
}
