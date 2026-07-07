// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Proves the editable target-retention path: the pure clamp mirrors settings.py's
// bounds, and a write onto the sample deck's config round-trips through the
// shared engine (set desiredRetention, read it back within bounds), exactly the
// seam Engine.setTargetRetention drives. AnkiBackend + Retention + StudySandbox
// and the generated protos are compiled into this standalone bundle.

import Foundation
import XCTest

final class RetentionSettingsTests: XCTestCase {
    /// The clamp coerces to the supported range and mirrors settings.py's bounds
    /// (MIN 0.7, MAX 0.97, DEFAULT 0.9), falling back to the default for NaN.
    func testClampBounds() {
        XCTAssertEqual(Retention.min, 0.7, accuracy: 1e-9)
        XCTAssertEqual(Retention.max, 0.97, accuracy: 1e-9)
        XCTAssertEqual(Retention.default, 0.9, accuracy: 1e-9)

        XCTAssertEqual(Retention.clamp(0.50), 0.70, accuracy: 1e-9, "below min clamps up")
        XCTAssertEqual(Retention.clamp(0.99), 0.97, accuracy: 1e-9, "above max clamps down")
        XCTAssertEqual(Retention.clamp(0.85), 0.85, accuracy: 1e-9, "in-range passes through")
        XCTAssertEqual(Retention.clamp(0.70), 0.70, accuracy: 1e-9, "the min itself is kept")
        XCTAssertEqual(Retention.clamp(0.97), 0.97, accuracy: 1e-9, "the max itself is kept")
        XCTAssertEqual(Retention.clamp(.nan), Retention.default, accuracy: 1e-9, "NaN falls back")
    }

    /// Round-trip: write desiredRetention onto the sample deck's own config group
    /// and read it back through the same seam Engine.targetRetention uses. Proves
    /// the legacy config write persists and stays within bounds, and that the
    /// deck keeps its own config (the user's default group is never touched).
    func testRetentionRoundTripOnSharedEngine() throws {
        let backend = try AnkiBackend()

        let bundle = Bundle(for: Self.self)
        guard let deckURL = StudySandbox.bundledDeckURL(in: bundle) else {
            return XCTFail("bundled collection.anki2 not found in the test bundle")
        }
        let sandbox = FileManager.default.temporaryDirectory
            .appendingPathComponent("PgrepRetentionTests-\(UUID().uuidString)", isDirectory: true)
        let staged = try StudySandbox.stage(from: deckURL, in: sandbox, freshCopy: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: sandbox) }

        try backend.openCollection(
            path: staged.collectionPath, mediaFolder: staged.mediaFolderPath
        )
        try backend.selectDeck(named: StudySandbox.studyDeckName)

        // The sample deck and its current config id (the seam retention rides on).
        let deckId = try backend.deckId(forName: "PGRE::Sample")
        XCTAssertNotEqual(deckId, 0, "the bundled collection should carry a PGRE::Sample deck")
        let configId = try backend.deckConfigsForUpdate(deckId: deckId).currentDeck.configID
        XCTAssertNotEqual(configId, 0, "the sample deck should have its own config group")

        func storedRetention() throws -> Double {
            let update = try backend.deckConfigsForUpdate(deckId: deckId)
            let match = update.allConfig.first { $0.config.id == update.currentDeck.configID }
            return Double(match?.config.config.desiredRetention ?? 0)
        }

        // A mid-range value round-trips and reads back within bounds.
        try backend.setDeckConfigDesiredRetention(configId: configId, retention: 0.85)
        XCTAssertEqual(try storedRetention(), 0.85, accuracy: 1e-4)
        XCTAssertTrue(
            (Retention.min...Retention.max).contains(try storedRetention()),
            "the stored retention should sit within the supported range"
        )

        // The bounds themselves round-trip.
        try backend.setDeckConfigDesiredRetention(configId: configId, retention: Retention.max)
        XCTAssertEqual(try storedRetention(), Retention.max, accuracy: 1e-4)
        try backend.setDeckConfigDesiredRetention(configId: configId, retention: Retention.min)
        XCTAssertEqual(try storedRetention(), Retention.min, accuracy: 1e-4)

        // The write leaves the deck on its own config (never the shared default).
        let after = try backend.deckConfigsForUpdate(deckId: deckId)
        XCTAssertEqual(
            after.currentDeck.configID, configId,
            "writing retention must not move the deck to a different config"
        )

        try backend.closeCollection()
    }
}
