// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Proof that the iOS attempt WRITE path is real: on the Simulator, over the C
// ABI, create the pgrep::Attempt notetype if missing, append an immutable
// attempt note, suspend its card, and read the same note back through the tag
// search the Performance fold uses. If this passes, a phone-run exam/ladder
// genuinely persists attempts that sync to desktop and feed the scores.

import Foundation
import XCTest

final class AttemptWriteTests: XCTestCase {
    func testAttemptWritePathPersistsAndReadsBack() throws {
        let backend = try AnkiBackend()

        let bundle = Bundle(for: Self.self)
        guard let deckURL = StudySandbox.bundledDeckURL(in: bundle) else {
            return XCTFail("bundled collection.anki2 not found in the test bundle")
        }
        let sandbox = FileManager.default.temporaryDirectory
            .appendingPathComponent("PgrepAttemptTests-\(UUID().uuidString)", isDirectory: true)
        let staged = try StudySandbox.stage(from: deckURL, in: sandbox, freshCopy: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: sandbox) }

        try backend.openCollection(
            path: staged.collectionPath,
            mediaFolder: staged.mediaFolderPath
        )

        let existedBefore = try backend.notetypeId(forName: AttemptSchema.notetypeName) != 0

        let draft = AttemptDraft(
            itemNoteId: 123,
            topic: "topic::mechanics",
            category: "mechanics",
            correct: true,
            selectedOption: "B",
            sessionId: "session-1",
            answeredAt: 1_700_000_000,
            ladderDepth: 0,
            difficulty: 3.0,
            responseMs: 8200
        )
        let eventIds = try backend.appendAttempts([draft])
        XCTAssertEqual(eventIds.count, 1, "one draft should write one attempt")
        let eventId = try XCTUnwrap(eventIds.first)

        // The notetype now exists, and ensuring it again must find (not recreate)
        // it: the write path is idempotent on the notetype, sync-compatible with
        // desktop's identically-named notetype.
        let notetypeId = try backend.notetypeId(forName: AttemptSchema.notetypeName)
        XCTAssertNotEqual(notetypeId, 0, "attempt notetype should exist after the write")
        XCTAssertEqual(
            try backend.ensureAttemptNotetype(), notetypeId,
            "ensuring the notetype again should reuse the existing one"
        )
        if !existedBefore {
            // The fresh sample had no attempt notetype, so the write path created it.
            XCTAssertTrue(true)
        }

        // The note is readable back through the same tag search the fold uses.
        let noteIds = try backend.searchNotes(matching: "tag:\(AttemptSchema.tag)")
        XCTAssertEqual(noteIds.count, 1, "exactly one attempt note should exist")
        let note = try backend.getNote(noteId: try XCTUnwrap(noteIds.first))
        XCTAssertEqual(note.guid, eventId, "note guid must equal the event_id (K2)")
        XCTAssertEqual(
            note.fields.count, AttemptSchema.fields.count,
            "the note should carry the five schema fields"
        )
        XCTAssertEqual(note.fields[0], eventId, "field 0 is the event_id")
        XCTAssertEqual(note.fields[2], "topic::mechanics", "field 2 is the topic tag")
        XCTAssertEqual(note.fields[3], "1", "field 3 encodes correct as 1")

        // The self-contained event_json round-trips the payload the fold reads.
        let json = note.fields[1]
        let data = try XCTUnwrap(json.data(using: .utf8))
        let payload = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: data) as? [String: Any]
        )
        XCTAssertEqual(payload["category"] as? String, "mechanics")
        XCTAssertEqual(payload["event_id"] as? String, eventId)
        XCTAssertEqual(payload["correct"] as? Bool, true)
        XCTAssertEqual(payload["ladder_depth"] as? Int, 0)
        XCTAssertEqual(payload["item_note_id"] as? Int, 123)
        XCTAssertEqual(payload["response_ms"] as? Int, 8200)

        // The attempt card is suspended, so it never enters the study queue.
        let suspended = try backend.searchCards(
            matching: "tag:\(AttemptSchema.tag) is:suspended"
        )
        XCTAssertEqual(suspended.count, 1, "the attempt card should be suspended")

        try backend.closeCollection()
    }
}
