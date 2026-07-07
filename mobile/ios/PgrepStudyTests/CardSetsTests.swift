// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Proof that the iOS Library / Card Sets read model and "Add a card" write path
// match the desktop (pylib/anki/pgrep/card_sets.py):
//
//   - the pure grouping (CardSets.group) orders sets by the blueprint, appends
//     any unrecognized category alphabetically (never dropping one), omits empty
//     categories, and keeps each set's cards in note-id order so cards[0] is the
//     stable deck-face preview;
//   - on the Simulator, over the C ABI, loadCardSets reads the seeded PGRE::Sample
//     cards back grouped by category, and addCard authors a Basic note into
//     PGRE::Generated tagged for its category, so it lands in the expected set
//     (and, being the same kind of note as a desktop-authored one, would sync).

import Foundation
import XCTest

final class CardSetsTests: XCTestCase {
    // MARK: Pure read-model grouping

    func testGroupOrdersByBlueprintAppendsUnknownAndKeepsNoteOrder() {
        // Categories deliberately out of blueprint order, note ids shuffled, a
        // non-blueprint category ("astro"), and an untagged row (-> "unknown").
        // The topic tag is not always first, mirroring how Anki stores tags.
        let rows: [CardSets.NoteRow] = [
            .init(noteId: 30, tags: ["pgrep::seeded", "topic::mechanics::dynamics", "pgrep::kind::conceptual"], front: "F30", back: "B30"),
            .init(noteId: 10, tags: ["topic::mechanics"], front: "F10", back: "B10"),
            .init(noteId: 20, tags: ["topic::quantum::formalism"], front: "F20", back: "B20"),
            .init(noteId: 5, tags: ["topic::atomic"], front: "F5", back: "B5"),
            .init(noteId: 40, tags: ["topic::astro"], front: "F40", back: "B40"),
            .init(noteId: 1, tags: ["misc"], front: "F1", back: "B1"),
        ]

        let sets = CardSets.group(rows: rows)

        // Blueprint order first (mechanics, quantum, atomic), then unrecognized
        // categories appended alphabetically ("astro" before "unknown").
        XCTAssertEqual(
            sets.map(\.category),
            ["mechanics", "quantum", "atomic", "astro", "unknown"],
            "sets should be blueprint-ordered with unrecognized categories appended alphabetically"
        )

        // Empty categories are omitted (nothing tagged electromagnetism/lab/...).
        XCTAssertFalse(sets.contains { $0.category == "electromagnetism" })
        XCTAssertFalse(sets.contains { $0.category == "lab" })

        // Display names come from the ported table (with a Title-Cased fallback).
        let byCategory = Dictionary(uniqueKeysWithValues: sets.map { ($0.category, $0) })
        XCTAssertEqual(byCategory["mechanics"]?.name, "Classical Mechanics")
        XCTAssertEqual(byCategory["quantum"]?.name, "Quantum Mechanics")
        XCTAssertEqual(byCategory["astro"]?.name, "Astro")
        XCTAssertEqual(byCategory["unknown"]?.name, "Unknown")

        // Cards keep note-id order, so cards[0] is the stable deck-face preview.
        // The first topic tag wins even when it is not first in the tag list.
        let mechanics = byCategory["mechanics"]
        XCTAssertEqual(mechanics?.cards.map(\.noteId), [10, 30])
        XCTAssertEqual(mechanics?.cards.first?.front, "F10")
        XCTAssertEqual(mechanics?.cards.count, 2)
    }

    func testDisplayNameAndTopicTagHelpers() {
        XCTAssertEqual(CardSets.displayName(for: "special_relativity"), "Special Relativity")
        XCTAssertEqual(CardSets.displayName(for: "optics_waves"), "Optics & Waves")
        // Fallback: underscores to spaces, Title-Cased.
        XCTAssertEqual(CardSets.displayName(for: "deep_inelastic"), "Deep Inelastic")

        // A bare slug is prefixed; an already-prefixed tag is kept verbatim.
        XCTAssertEqual(CardSets.topicTag(for: "mechanics"), "topic::mechanics")
        XCTAssertEqual(CardSets.topicTag(for: "topic::mechanics::sub"), "topic::mechanics::sub")
    }

    // MARK: On-Simulator read + write over the shared engine

    func testLoadCardSetsAndAddCardLandsInExpectedSet() throws {
        let backend = try AnkiBackend()

        let bundle = Bundle(for: Self.self)
        guard let deckURL = StudySandbox.bundledDeckURL(in: bundle) else {
            return XCTFail("bundled collection.anki2 not found in the test bundle")
        }
        let sandbox = FileManager.default.temporaryDirectory
            .appendingPathComponent("PgrepCardSetsTests-\(UUID().uuidString)", isDirectory: true)
        let staged = try StudySandbox.stage(from: deckURL, in: sandbox, freshCopy: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: sandbox) }

        try backend.openCollection(
            path: staged.collectionPath,
            mediaFolder: staged.mediaFolderPath
        )

        // 1. The seeded sample reads back as blueprint-ordered category sets, each
        //    with real cards and its ported display name.
        let sets = try backend.loadCardSets()
        XCTAssertFalse(sets.isEmpty, "the seeded sample deck should yield card sets")
        XCTAssertEqual(sets.first?.category, "mechanics", "mechanics leads the blueprint")
        for set in sets {
            XCTAssertTrue(
                Blueprint.byCategory[set.category] != nil,
                "every seeded set is a recognized blueprint category (got \(set.category))"
            )
            XCTAssertFalse(set.cards.isEmpty, "an omitted-if-empty set should never be empty")
            XCTAssertEqual(set.name, CardSets.displayName(for: set.category))
        }
        // The categories present appear in blueprint order.
        let expectedOrder = Blueprint.slugs.filter { slug in sets.contains { $0.category == slug } }
        XCTAssertEqual(sets.map(\.category), expectedOrder, "sets are in blueprint order")

        let target = "optics_waves"
        let before = try XCTUnwrap(
            sets.first { $0.category == target }, "the sample should seed an \(target) set"
        )
        let beforeCount = before.cards.count

        // 2. Author a card (with padding, to prove the front/back are trimmed like
        //    author_seed's front.strip()/back.strip()).
        let front = "  Snell's law: \\(n_1 \\sin\\theta_1 = n_2 \\sin\\theta_2\\)  "
        let back = "  Refraction at an interface.  "
        let newId = try backend.addCard(category: target, front: front, back: back)
        XCTAssertNotEqual(newId, 0, "addCard should return the new note id")

        // 3. The new note is a Basic note in PGRE::Generated, tagged for the
        //    category with the seed-authored marker, fields trimmed. This is the
        //    same shape a desktop-authored seed card has (so it merges on sync).
        let basicId = try backend.notetypeId(forName: CardSets.basicNotetypeName)
        let note = try backend.getNote(noteId: newId)
        XCTAssertEqual(note.notetypeID, basicId, "authored card uses the Basic notetype")
        XCTAssertEqual(note.fields.first, "Snell's law: \\(n_1 \\sin\\theta_1 = n_2 \\sin\\theta_2\\)")
        XCTAssertEqual(note.fields.count > 1 ? note.fields[1] : "", "Refraction at an interface.")
        XCTAssertTrue(note.tags.contains(CardSets.seedTag), "carries the seed-authored tag")
        XCTAssertTrue(note.tags.contains("topic::\(target)"), "carries the category topic tag")

        let generated = try backend.searchNotes(
            matching: "deck:\"\(CardSets.generatedDeckName)\" tag:topic::\(target)"
        )
        XCTAssertTrue(generated.contains(newId), "the card lands in the PGRE::Generated deck")

        // 4. Re-reading the sets, the card is in the EXPECTED category set (and no
        //    other), and that set's count grew by exactly one.
        let after = try backend.loadCardSets()
        let afterTarget = try XCTUnwrap(after.first { $0.category == target })
        XCTAssertEqual(afterTarget.cards.count, beforeCount + 1, "the target set grew by one")
        let landed = try XCTUnwrap(
            afterTarget.cards.first { $0.noteId == newId },
            "the authored card should appear in its category set"
        )
        XCTAssertEqual(landed.front, "Snell's law: \\(n_1 \\sin\\theta_1 = n_2 \\sin\\theta_2\\)")
        XCTAssertEqual(landed.back, "Refraction at an interface.")
        for set in after where set.category != target {
            XCTAssertFalse(
                set.cards.contains { $0.noteId == newId },
                "the card should not appear in any other set (\(set.category))"
            )
        }

        try backend.closeCollection()
    }
}
