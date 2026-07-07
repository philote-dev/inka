// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Library: the Card Sets browser (design_handoff_card_sets, ts/routes/pgrep/
// library + CardWheel.svelte). AI is off on the phone, so this is the Card Sets
// surface (never the AI-on calibration walkthrough, which is a separate task).
//
// A native SwiftUI analog of the web "wheel", not a reproduction of its FLIP/3D
// animation: a horizontal one-up carousel selects a category set (mirroring the
// wheel's phone one-up mode), and the selected set's cards read below as a
// scroll of flip cards (tap to reveal the back), typeset with the shared
// MathText. "Add a card" authors the learner's own front/back as-is into the
// set (no AI) via Engine.addCard, then reloads so the new card lands in its set
// and the counts update, exactly like the desktop composer.

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
            summary(sets)
            carousel(sets)
                .frame(height: 210)
            Divider().background(Theme.border)
            cardsList
        }
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
