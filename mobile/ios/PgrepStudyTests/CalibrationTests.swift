// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Proof that the iOS calibration port matches the desktop:
//
//   - the pure gate derivation (Calibration), a port of
//     pylib/anki/pgrep/calibration.py: covered categories are the distinct
//     blueprint categories with a learner-authored card, and the status is
//     calibrated once every category is covered OR the sticky flag is set, with
//     set-on-completion (shouldPersist) so a later deletion never re-locks it;
//   - the embedded evidence (CalibrationEvidence), a port of
//     pylib/anki/pgrep/calibration_evidence.py, including the {p, o} ->
//     {predicted, observed} mapping bridge to ReliabilityDiagramView and the
//     Codable shape matching the desktop JSON;
//   - on the Simulator, over the C ABI, authoring one card per blueprint category
//     flips calibrationStatus() to calibrated, and the sticky flag survives
//     deleting every authored card afterwards.

import Foundation
import XCTest

final class CalibrationTests: XCTestCase {
    // MARK: Covered categories (_covered_categories)

    func testCoveredCategoriesCountsDistinctBlueprintCategories() {
        // Two mechanics cards (a bare category tag and a subtopic) count once; a
        // quantum card counts; a non-blueprint category ("astro") and an untagged
        // note ("unknown") never count. The topic tag is not always first.
        let tagLists: [[String]] = [
            ["pgrep::seed-authored", "topic::mechanics"],
            ["pgrep::seed-authored", "topic::mechanics::dynamics"],
            ["topic::quantum::formalism", "pgrep::seed-authored"],
            ["pgrep::seed-authored", "topic::astro"],
            ["pgrep::seed-authored", "misc"],
        ]
        let covered = Calibration.coveredCategories(fromTagLists: tagLists)
        XCTAssertEqual(covered, ["mechanics", "quantum"])
    }

    func testCoveredCategoriesEmptyWhenNothingAuthored() {
        XCTAssertTrue(Calibration.coveredCategories(fromTagLists: []).isEmpty)
    }

    // MARK: Status derivation (calibration_status)

    func testRequiredEqualsBlueprintCategoryCount() {
        // One authored card per blueprint category calibrates the collection.
        XCTAssertEqual(Calibration.requiredCategories, Blueprint.slugs.count)
        XCTAssertEqual(Calibration.requiredCategories, 9)
    }

    func testStatusUncalibratedBelowFullCoverage() {
        let status = Calibration.status(authored: 8, storedCalibrated: false)
        XCTAssertFalse(status.calibrated)
        XCTAssertEqual(status.authored, 8)
        XCTAssertEqual(status.required, 9)
        XCTAssertFalse(status.shouldPersist, "nothing to persist below full coverage")
    }

    func testStatusCalibratesAndPersistsOnCompletion() {
        // Reaching full coverage calibrates, and signals the sticky write.
        let status = Calibration.status(authored: 9, storedCalibrated: false)
        XCTAssertTrue(status.calibrated)
        XCTAssertEqual(status.authored, 9)
        XCTAssertTrue(status.shouldPersist, "first completion records the durable flag")
    }

    func testStatusStickyFlagKeepsCalibratedAfterDeletion() {
        // The stored flag holds even when authored drops back below required, and
        // it does not re-trigger a write (already stored).
        let status = Calibration.status(authored: 3, storedCalibrated: true)
        XCTAssertTrue(status.calibrated, "the sticky flag keeps calibration durable")
        XCTAssertEqual(status.authored, 3)
        XCTAssertFalse(status.shouldPersist, "the flag is already stored")
    }

    func testStatusAlreadyStoredAtFullCoverageDoesNotRepersist() {
        let status = Calibration.status(authored: 9, storedCalibrated: true)
        XCTAssertTrue(status.calibrated)
        XCTAssertFalse(status.shouldPersist)
    }

    // MARK: Embedded evidence (calibration_evidence)

    func testEmbeddedEvidenceMatchesDesktopConstants() throws {
        let evidence = CalibrationEvidence.embedded

        // Memory: default FSRS-6 on held-out reviews (L5.1).
        XCTAssertEqual(evidence.memory.points.count, 10)
        XCTAssertEqual(evidence.memory.brier, 0.23376769284759738, accuracy: 1e-15)
        XCTAssertEqual(evidence.memory.n, 7503)
        XCTAssertEqual(evidence.memory.date, "2026-07-05")
        XCTAssertEqual(
            evidence.memory.note,
            "Validated on held-out reviews. Default FSRS, slightly overconfident."
        )
        XCTAssertEqual(
            evidence.memory.source,
            "Held-out reviews from the anki-revlogs-10k sample (4 users, time-split)"
        )
        XCTAssertEqual(
            evidence.memory.method,
            "Default FSRS-6 (fsrs-rs 5.2.0) retrievability vs recall; binning-free Brier"
        )
        // The first/last points mirror calibration_evidence.MEMORY_RELIABILITY_POINTS.
        let memFirst = try XCTUnwrap(evidence.memory.points.first)
        XCTAssertEqual(memFirst.p, 0.5537578246385091, accuracy: 1e-15)
        XCTAssertEqual(memFirst.o, 0.31025299600532624, accuracy: 1e-15)
        let memLast = try XCTUnwrap(evidence.memory.points.last)
        XCTAssertEqual(memLast.p, 0.9798395923438424, accuracy: 1e-15)
        XCTAssertEqual(memLast.o, 0.668, accuracy: 1e-15)

        // Performance: held-out synthetic pipeline validation (L5.2).
        XCTAssertEqual(evidence.performance.points.count, 10)
        XCTAssertEqual(evidence.performance.brier, 0.17523368467276343, accuracy: 1e-15)
        XCTAssertEqual(evidence.performance.n, 160)
        XCTAssertEqual(evidence.performance.date, "2026-07-05")
        XCTAssertEqual(
            evidence.performance.note,
            "Methodology validated on held-out synthetic (n=1 cohort)."
        )
        XCTAssertEqual(
            evidence.performance.source,
            "Held-out synthetic exam-style outcomes (pipeline validation)"
        )
        XCTAssertEqual(
            evidence.performance.method,
            "PFA logistic + beta calibration on a held-out split; binning-free Brier"
        )
        let perfFirst = try XCTUnwrap(evidence.performance.points.first)
        XCTAssertEqual(perfFirst.p, 0.42041089306686397, accuracy: 1e-15)
        XCTAssertEqual(perfFirst.o, 0.3125, accuracy: 1e-15)
    }

    func testReliabilityPointBridgeMapsKeysInOrder() {
        // The bridge maps the evidence's {p, o} to the diagram's {predicted,
        // observed}, preserving order and values (the reviewer of
        // ReliabilityDiagramView flagged this bridge is needed).
        let layer = CalibrationEvidence.embedded.memory
        let mapped = layer.reliabilityPoints
        XCTAssertEqual(mapped.count, layer.points.count)
        for (point, reliability) in zip(layer.points, mapped) {
            XCTAssertEqual(reliability.predicted, point.p, accuracy: 1e-15)
            XCTAssertEqual(reliability.observed, point.o, accuracy: 1e-15)
        }
        // The mapped Brier is what the diagram formats (round3), so it matches the
        // desktop caption.
        XCTAssertEqual(ReliabilityDiagram.formatBrier(layer.brier), "0.234")
    }

    func testLayerDecodesFromDesktopJsonShape() throws {
        // The Codable keys match calibration_evidence.py's `{p, o}` point shape
        // and the layer fields, so an iOS decode of the desktop payload round-trips.
        let json = """
        {
          "points": [{"p": 0.5, "o": 0.4}, {"p": 0.9, "o": 0.85}],
          "brier": 0.12,
          "n": 42,
          "note": "note text",
          "source": "source text",
          "method": "method text",
          "date": "2026-07-05"
        }
        """
        let layer = try JSONDecoder().decode(CalibrationLayer.self, from: Data(json.utf8))
        XCTAssertEqual(layer.points, [CalibrationPoint(p: 0.5, o: 0.4), CalibrationPoint(p: 0.9, o: 0.85)])
        XCTAssertEqual(layer.brier, 0.12, accuracy: 1e-12)
        XCTAssertEqual(layer.n, 42)
        XCTAssertEqual(layer.note, "note text")
        XCTAssertEqual(layer.reliabilityPoints.first, ReliabilityPoint(predicted: 0.5, observed: 0.4))
    }

    // MARK: On-Simulator status over the shared engine

    func testCalibrationStatusFlipsAndStaysSticky() throws {
        let backend = try AnkiBackend()

        let bundle = Bundle(for: Self.self)
        guard let deckURL = StudySandbox.bundledDeckURL(in: bundle) else {
            return XCTFail("bundled collection.anki2 not found in the test bundle")
        }
        let sandbox = FileManager.default.temporaryDirectory
            .appendingPathComponent("PgrepCalibrationTests-\(UUID().uuidString)", isDirectory: true)
        let staged = try StudySandbox.stage(from: deckURL, in: sandbox, freshCopy: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: sandbox) }

        try backend.openCollection(
            path: staged.collectionPath,
            mediaFolder: staged.mediaFolderPath
        )
        defer { try? backend.closeCollection() }

        // 1. A fresh (seeded-only) collection is honestly uncalibrated: the bundled
        //    sample cards carry pgrep::seeded, not the learner-authored seed tag.
        let initial = try backend.calibrationStatus()
        XCTAssertEqual(initial.required, 9)
        XCTAssertFalse(initial.calibrated, "seeded-only sample calibrates nothing")

        // 2. Author one card in every blueprint category (the generation-effect
        //    act). Each is a real seed-authored Basic note in PGRE::Generated.
        for slug in Blueprint.slugs {
            _ = try backend.addCard(
                category: slug,
                front: "My own \(slug) card",
                back: "In my own words."
            )
        }

        // 3. Full coverage calibrates the collection.
        let done = try backend.calibrationStatus()
        XCTAssertEqual(done.authored, 9, "every blueprint category now has an authored card")
        XCTAssertTrue(done.calibrated, "one authored card per category calibrates")

        // 4. Delete every learner-authored card. Coverage drops to zero, but the
        //    sticky flag (recorded on completion) keeps the collection calibrated,
        //    so removing a card later never re-locks it.
        let authoredNotes = try backend.searchNotes(matching: Calibration.searchQuery)
        XCTAssertFalse(authoredNotes.isEmpty)
        _ = try backend.removeNotes(noteIds: authoredNotes)

        let sticky = try backend.calibrationStatus()
        XCTAssertEqual(sticky.authored, 0, "all authored cards were removed")
        XCTAssertTrue(sticky.calibrated, "the sticky flag keeps calibration durable")
    }
}
