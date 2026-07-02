// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// The required proof for L0: run Anki's SHARED Rust engine on the iOS Simulator
// through the C ABI and drive a full review loop against the bundled sample
// deck. If this passes on the simulator, the engine-on-phone seam is real.

import Foundation
import XCTest

// The engine bridge (AnkiBackend, StudySandbox) and the generated protobuf
// types are compiled directly into this standalone test bundle, so no module
// import is needed.

final class EngineSmokeTests: XCTestCase {
    /// Full review loop: open backend -> stage + open collection -> queue ->
    /// note -> answer -> confirm the queue advanced -> seam check -> close.
    func testReviewLoopOnSharedEngine() throws {
        // 1. Open the backend with default init bytes.
        let backend = try AnkiBackend()

        // 2. Stage a *fresh* copy of the bundled deck in a temp sandbox and
        //    create a media folder next to it.
        let bundle = Bundle(for: Self.self)
        guard let deckURL = StudySandbox.bundledDeckURL(in: bundle) else {
            return XCTFail("bundled collection.anki2 not found in the test bundle")
        }
        let sandbox = FileManager.default.temporaryDirectory
            .appendingPathComponent("PgrepStudyTests-\(UUID().uuidString)", isDirectory: true)
        let staged = try StudySandbox.stage(from: deckURL, in: sandbox, freshCopy: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: sandbox) }

        // 3. OpenCollection must succeed.
        XCTAssertNoThrow(
            try backend.openCollection(
                path: staged.collectionPath,
                mediaFolder: staged.mediaFolderPath
            ),
            "OpenCollection should succeed against the bundled deck"
        )

        // 3b. Select the PGRE deck as current. A freshly opened collection
        //     defaults to the empty "Default" deck, so the scheduler would
        //     otherwise queue nothing (just like desktop before a deck is
        //     picked).
        XCTAssertNoThrow(
            try backend.selectDeck(named: StudySandbox.studyDeckName),
            "selecting the PGRE deck should succeed"
        )

        // 4. GetQueuedCards returns at least one card.
        let firstQueue = try backend.getQueuedCards(fetchLimit: 10)
        XCTAssertGreaterThanOrEqual(
            firstQueue.cards.count, 1,
            "expected at least one queued card in the sample deck"
        )
        let firstCard = try XCTUnwrap(firstQueue.cards.first).card
        let firstNewCount = firstQueue.newCount

        // 5. GetNote returns non-empty fields (Front/Back).
        let note = try backend.getNote(noteId: firstCard.noteID)
        XCTAssertFalse(note.fields.isEmpty, "note should have fields")
        XCTAssertFalse(
            (note.fields.first ?? "").isEmpty,
            "the Front field should not be empty"
        )

        // 6. AnswerCard("Good") returns without error.
        var answer = Anki_Scheduler_CardAnswer()
        answer.cardID = firstCard.id
        answer.currentState = try XCTUnwrap(firstQueue.cards.first).states.current
        answer.newState = try XCTUnwrap(firstQueue.cards.first).states.good
        answer.rating = .good
        answer.answeredAtMillis = Int64(Date().timeIntervalSince1970 * 1000)
        answer.millisecondsTaken = 1000
        XCTAssertNoThrow(try backend.answerCard(answer), "AnswerCard should not error")

        // 7. A follow-up GetQueuedCards shows the queue advanced: either the
        //    front card changed, the queue emptied, or the new count dropped.
        let secondQueue = try backend.getQueuedCards(fetchLimit: 10)
        let advanced = secondQueue.cards.isEmpty
            || secondQueue.cards.first?.card.id != firstCard.id
            || secondQueue.newCount < firstNewCount
        XCTAssertTrue(advanced, "the queue should advance after answering a card")

        // 8. PgrepSeamCheck proves the shared engine round-trips through the C ABI.
        XCTAssertEqual(
            try backend.pgrepSeamCheck(),
            "pgrep seam OK (Rust)",
            "the Rust seam marker should round-trip through the C ABI"
        )

        // 9. Tidy up.
        XCTAssertNoThrow(try backend.closeCollection(), "CloseCollection should not error")
    }
}
