// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// The Library / Card Sets read model + "Add a card" write path for the iOS
// companion. A faithful port of pylib/anki/pgrep/card_sets.py (list_card_sets +
// add_card, which delegates to generation.author_seed):
//
//   - list_card_sets: group the learner's Basic topic-tagged cards in the seeded
//     PGRE::Sample and authored PGRE::Generated decks into one set per blueprint
//     category, in blueprint order (unrecognized categories appended
//     alphabetically), dropping categories with no cards. Real counts and a real
//     deck-face preview (cards[0].front); no AI, no scheduler.
//   - add_card -> author_seed: the learner's own front/back go straight into the
//     PGRE::Generated deck as a new Basic note tagged [pgrep::seed-authored,
//     topic::<category>], so a card added on the phone is the same kind of note
//     as a desktop-added one and merges on sync, landing in the right set and
//     (once studied) Memory / Coverage.
//
// The grouping / ordering / naming is pure and unit-testable (see CardSets.group
// and CardSetsTests); the engine reads and writes via the note RPCs in the
// AnkiBackend extension below, mirroring how AttemptWriter.swift adds notes.
//
// The blueprint order and the category display names are duplicated here on
// purpose, the same cross-language boundary duplication the L1 contract mandates
// (docs_pgrep/contracts/L1-coordination-schema.md §1); the order reuses the
// Blueprint table already ported in MemoryScore.swift.

import Foundation

/// One browsable card in a set. Mirrors list_card_sets' `{note_id, front, back}`.
struct CardSetCard: Sendable, Equatable, Identifiable {
    var noteId: Int64
    var front: String
    var back: String

    var id: Int64 { noteId }
}

/// One category's set of cards. Mirrors a list_card_sets entry
/// (`{category, name, cards}`).
struct CardSet: Sendable, Equatable, Identifiable {
    var category: String
    var name: String
    var cards: [CardSetCard]

    var id: String { category }
}

enum CardSets {
    /// The decks a card set draws from: the seeded sample deck and the authored /
    /// AI-generated deck. Mirrors card_sets.SET_DECKS.
    static let setDecks = ["PGRE::Sample", "PGRE::Generated"]

    /// The deck a learner-authored card lands in. Mirrors
    /// generation.GENERATED_DECK_NAME.
    static let generatedDeckName = "PGRE::Generated"

    /// The seed-authored marker tag on every authored card. Mirrors
    /// generation.SEED_TAG (distinct from the seeder's pgrep::seeded).
    static let seedTag = "pgrep::seed-authored"

    /// The Basic notetype a card set's notes (and authored cards) use. Mirrors
    /// generation._basic / seed's col.models.by_name("Basic").
    static let basicNotetypeName = "Basic"

    /// Category slug -> display name. Mirrors card_sets.CATEGORY_NAMES so a
    /// category reads the same on every surface. Duplicated rather than derived
    /// from the manifold labels on purpose (that table is presentation-coupled to
    /// the 3D map, per blueprint.py on intentional per-boundary duplication).
    static let categoryNames: [String: String] = [
        "mechanics": "Classical Mechanics",
        "electromagnetism": "Electromagnetism",
        "quantum": "Quantum Mechanics",
        "thermodynamics": "Thermo & Stat Mech",
        "atomic": "Atomic Physics",
        "optics_waves": "Optics & Waves",
        "special_relativity": "Special Relativity",
        "lab": "Laboratory Methods",
        "specialized": "Specialized Topics",
    ]

    /// Human name for a category slug (Title-Cased fallback for the unexpected).
    /// Mirrors card_sets._display_name.
    static func displayName(for category: String) -> String {
        if let name = categoryNames[category] { return name }
        return category
            .split(separator: "_", omittingEmptySubsequences: true)
            .map { $0.prefix(1).uppercased() + $0.dropFirst().lowercased() }
            .joined(separator: " ")
    }

    /// The topic tag for a category slug. Mirrors generation._topic_tag: a bare
    /// slug becomes "topic::<slug>"; an already-prefixed tag is kept verbatim.
    static func topicTag(for category: String) -> String {
        category.lowercased().hasPrefix(Topic.prefix) ? category : "\(Topic.prefix)\(category)"
    }

    /// The Anki search that finds a set's candidate notes. Mirrors
    /// list_card_sets' query exactly: Basic notes in the set decks that carry a
    /// topic tag.
    static var searchQuery: String {
        let decks = setDecks.map { "deck:\"\($0)\"" }.joined(separator: " OR ")
        return "note:\(basicNotetypeName) (\(decks)) tag:\(Topic.prefix)*"
    }

    /// A candidate note read from the engine, before grouping.
    struct NoteRow: Sendable, Equatable {
        var noteId: Int64
        var tags: [String]
        var front: String
        var back: String
    }

    /// Group candidate notes into one set per category, in blueprint order (any
    /// unrecognized category appended alphabetically so nothing is dropped),
    /// omitting categories with no cards. A line-for-line port of
    /// list_card_sets' grouping. Rows are sorted by note id first, so each set's
    /// `cards[0]` is the stable, insertion-order deck-face preview.
    static func group(rows: [NoteRow]) -> [CardSet] {
        var byCategory: [String: [CardSetCard]] = [:]
        for row in rows.sorted(by: { $0.noteId < $1.noteId }) {
            let category = Topic.category(forTags: row.tags)
            byCategory[category, default: []].append(
                CardSetCard(noteId: row.noteId, front: row.front, back: row.back)
            )
        }

        var ordered = Blueprint.slugs.filter { byCategory[$0] != nil }
        ordered += byCategory.keys.filter { !Blueprint.slugs.contains($0) }.sorted()

        return ordered.map { category in
            CardSet(
                category: category,
                name: displayName(for: category),
                cards: byCategory[category] ?? []
            )
        }
    }
}

extension AnkiBackend {
    /// Read the learner's card sets, a port of card_sets.list_card_sets over the
    /// note RPCs: find the Basic topic-tagged notes in the set decks, read each
    /// note's tags/front/back, and group them into one set per category in
    /// blueprint order. Note ids are sorted ascending so `cards[0]` is the stable
    /// deck-face preview, matching desktop's `sorted(find_notes(...))`. A stray
    /// match without both fields is skipped (the desktop Front/Back guard).
    func loadCardSets() throws -> [CardSet] {
        let noteIds = try searchNotes(matching: CardSets.searchQuery).sorted()
        var rows: [CardSets.NoteRow] = []
        rows.reserveCapacity(noteIds.count)
        for nid in noteIds {
            let note = try getNote(noteId: nid)
            // Guard the field read: a stray non-Basic match would lack Front/Back.
            guard note.fields.count >= 2 else { continue }
            rows.append(CardSets.NoteRow(
                noteId: note.id,
                tags: note.tags,
                front: note.fields[0],
                back: note.fields[1]
            ))
        }
        return CardSets.group(rows: rows)
    }

    /// Author one card into a category's set, as-is (no AI). A port of
    /// card_sets.add_card -> generation.author_seed: a new Basic note whose
    /// trimmed Front/Back go straight into the PGRE::Generated deck, tagged
    /// [pgrep::seed-authored, topic::<category>]. Returns the new note id. The
    /// notetype and deck are resolved (and bootstrapped only on a never-synced
    /// phone that lacks them) exactly like the desktop seed path, so an
    /// iOS-authored card is the same kind of note as a desktop one.
    @discardableResult
    func addCard(category: String, front: String, back: String) throws -> Int64 {
        let notetypeId = try ensureBasicNotetype()
        let deckId = try ensureGeneratedDeck()

        var note = Anki_Notes_Note()
        note.notetypeID = notetypeId
        note.fields = [
            front.trimmingCharacters(in: .whitespacesAndNewlines),
            back.trimmingCharacters(in: .whitespacesAndNewlines),
        ]
        note.tags = [CardSets.seedTag, CardSets.topicTag(for: category)]

        let response = try addNote(note, deckId: deckId)
        return response.noteID
    }

    /// The `Basic` notetype id, preferring the collection's existing (synced) one
    /// and only bootstrapping a schema-standard Basic on a never-synced phone
    /// that somehow lacks it. Mirrors AttemptWriter.ensureAttemptNotetype's
    /// find-then-create pattern; the shipped path always finds the synced Basic
    /// (the bundled sample collection ships with it, like desktop).
    func ensureBasicNotetype() throws -> Int64 {
        let existing = try notetypeId(forName: CardSets.basicNotetypeName)
        if existing != 0 { return existing }

        var notetype = Anki_Notetypes_Notetype()
        notetype.name = CardSets.basicNotetypeName
        var config = Anki_Notetypes_Notetype.Config()
        config.kind = .normal
        config.sortFieldIdx = 0
        notetype.config = config
        notetype.fields = ["Front", "Back"].map { name in
            var field = Anki_Notetypes_Notetype.Field()
            field.name = name
            return field
        }
        var template = Anki_Notetypes_Notetype.Template()
        template.name = "Card 1"
        template.config.qFormat = "{{Front}}"
        template.config.aFormat = "{{FrontSide}}\n\n<hr id=answer>\n\n{{Back}}"
        notetype.templates = [template]
        return try addNotetype(notetype)
    }

    /// The `PGRE::Generated` deck id, creating it (with its `PGRE` parent) when
    /// missing. Mirrors generation's `col.decks.id(GENERATED_DECK_NAME)`, which
    /// creates the deck on first author.
    func ensureGeneratedDeck() throws -> Int64 {
        let existing = try deckId(forName: CardSets.generatedDeckName)
        if existing != 0 { return existing }
        var deck = try newDeck()
        deck.name = CardSets.generatedDeckName
        return try addDeck(deck)
    }
}
