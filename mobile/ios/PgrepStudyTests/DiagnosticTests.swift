// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Pins the Diagnostic's pure placement core (Diagnostic), a port of
// pylib/anki/pgrep/diagnostic.py: the strong/rusty rule (quick-check decisive,
// else the FSRS-R Memory prior, else rusty, with no cold bucket), the quick-check
// grading, the blueprint-ordered fold, the persisted snapshot shape, and the
// ported quick-check content. The SwiftUI DiagnosticView that drives this against
// the engine is not unit-tested here, matching how StudySession / ChoiceList pin
// their logic while their views stay in the app target. Deterministic by
// construction: pure functions only.

import XCTest

final class DiagnosticTests: XCTestCase {
    // MARK: Placement rule (_placement_for)

    func testPlacementQuickCheckIsDecisiveOverMemoryPrior() {
        // A fresh correct answer places strong even with no (or zero) memory; a
        // fresh wrong answer places rusty even when FSRS still rates the old cards
        // highly. The quick check overrides the prior either way.
        XCTAssertEqual(Diagnostic.placement(memoryPoint: nil, outcome: .correct), .strong)
        XCTAssertEqual(Diagnostic.placement(memoryPoint: 0.0, outcome: .correct), .strong)
        XCTAssertEqual(Diagnostic.placement(memoryPoint: 0.99, outcome: .wrong), .rusty)
        XCTAssertEqual(Diagnostic.placement(memoryPoint: nil, outcome: .wrong), .rusty)
    }

    func testPlacementFallsBackToMemoryPrior() {
        // With no quick check, a Memory point at or above the threshold leans
        // strong; below it leans rusty.
        XCTAssertEqual(Diagnostic.placement(memoryPoint: 0.7, outcome: nil), .strong)
        XCTAssertEqual(Diagnostic.placement(memoryPoint: 0.85, outcome: nil), .strong)
        XCTAssertEqual(Diagnostic.placement(memoryPoint: 0.699, outcome: nil), .rusty)
        XCTAssertEqual(Diagnostic.placement(memoryPoint: 0.0, outcome: nil), .rusty)
    }

    func testPlacementDefaultsRustyWithNoSignal() {
        // Post-undergraduate persona: no cold bucket, so no signal means rusty.
        XCTAssertEqual(Diagnostic.placement(memoryPoint: nil, outcome: nil), .rusty)
    }

    func testStrongMemoryPointThreshold() {
        XCTAssertEqual(Diagnostic.strongMemoryPoint, 0.7)
    }

    // MARK: Quick-check grading

    func testOutcomeGrading() {
        XCTAssertEqual(Diagnostic.outcome(selected: 2, answer: 2), .correct)
        XCTAssertEqual(Diagnostic.outcome(selected: 1, answer: 2), .wrong)
        // A never-answered check yields no outcome, so placement uses the prior.
        XCTAssertNil(Diagnostic.outcome(selected: nil, answer: 2))
    }

    // MARK: Fold (place)

    func testPlaceReturnsEveryBlueprintCategoryInOrder() {
        let placed = Diagnostic.place(answers: [:], memoryPoints: [:])
        XCTAssertEqual(placed.map(\.category), Blueprint.slugs)
        // No signal anywhere: every category is rusty (no cold bucket).
        XCTAssertTrue(placed.allSatisfy { $0.placement == .rusty })
    }

    func testPlaceQuickCheckDecisiveInTheFold() {
        // mechanics: a correct pick places strong even with no memory.
        // quantum: a wrong pick places rusty even with high memory.
        let placed = Diagnostic.place(
            answers: [
                "mechanics": correctIndex(for: "mechanics"),
                "quantum": wrongIndex(for: "quantum"),
            ],
            memoryPoints: ["quantum": 0.95]
        )
        let byCategory = placement(of: placed)
        XCTAssertEqual(byCategory["mechanics"], .strong)
        XCTAssertEqual(byCategory["quantum"], .rusty)
    }

    func testPlaceFallsBackToMemoryWhenUnanswered() {
        // No answers: each category uses the memory prior; exactly the threshold
        // is strong, just below is rusty, and no memory is rusty.
        let placed = Diagnostic.place(
            answers: [:],
            memoryPoints: ["mechanics": 0.7, "quantum": 0.69, "atomic": 0.9]
        )
        let byCategory = placement(of: placed)
        XCTAssertEqual(byCategory["mechanics"], .strong)
        XCTAssertEqual(byCategory["quantum"], .rusty)
        XCTAssertEqual(byCategory["atomic"], .strong)
        XCTAssertEqual(byCategory["lab"], .rusty)
    }

    // MARK: Snapshot (persisted config shape)

    func testSnapshotShapeMatchesDesktopConfig() {
        let placed = [
            PlacedTopic(category: "mechanics", placement: .strong),
            PlacedTopic(category: "quantum", placement: .rusty),
        ]
        XCTAssertEqual(
            Diagnostic.snapshot(from: placed),
            ["mechanics": "strong", "quantum": "rusty"]
        )
    }

    func testConfigKeyMatchesDesktop() {
        // Must equal diagnostic.DIAGNOSTIC_CONFIG_KEY so a phone-written completion
        // is what the desktop pgrep_diagnostic_status reads (and vice versa).
        XCTAssertEqual(Diagnostic.configKey, "pgrep_diagnostic")
    }

    // MARK: Quick-check content (ported constant)

    func testQuickChecksCoverEveryBlueprintCategory() {
        for slug in Blueprint.slugs {
            XCTAssertNotNil(Diagnostic.quickChecks[slug], "missing quick check for \(slug)")
        }
        XCTAssertEqual(Diagnostic.quickChecks.count, Blueprint.slugs.count)
    }

    func testQuickCheckAnswersAreInRangeAndNonEmpty() {
        for (slug, check) in Diagnostic.quickChecks {
            XCTAssertFalse(check.prompt.isEmpty, "\(slug) has an empty prompt")
            XCTAssertFalse(check.choices.isEmpty, "\(slug) has no choices")
            XCTAssertTrue(check.choices.indices.contains(check.answer), "\(slug) answer out of range")
        }
    }

    func testQuickCheckKeysMatchDesktop() {
        // Spot-check answer keys against diagnostic.QUICK_CHECKS so a silent
        // content drift (which would corrupt the placement) is caught.
        XCTAssertEqual(Diagnostic.quickChecks["mechanics"]?.answer, 0)
        XCTAssertEqual(Diagnostic.quickChecks["mechanics"]?.choices.first, "\\(gt\\)")
        XCTAssertEqual(Diagnostic.quickChecks["electromagnetism"]?.answer, 1)
        XCTAssertEqual(Diagnostic.quickChecks["quantum"]?.answer, 1)
        XCTAssertEqual(Diagnostic.quickChecks["special_relativity"]?.answer, 2)
        XCTAssertEqual(Diagnostic.quickChecks["lab"]?.answer, 1)
    }

    // MARK: Topics + check items (topics)

    func testTopicsInBlueprintOrderWithStoredPlacementAndChecks() {
        let topics = Diagnostic.topics(
            stored: ["mechanics": "strong", "quantum": "bogus"],
            nCards: ["mechanics": 12]
        )
        XCTAssertEqual(topics.map(\.category), Blueprint.slugs)

        let mechanics = topics.first { $0.category == "mechanics" }
        XCTAssertEqual(mechanics?.placement, .strong)
        XCTAssertEqual(mechanics?.nCards, 12)
        XCTAssertNotNil(mechanics?.check)

        // An unrecognized stored value reads as no placement (the _PLACEMENTS guard).
        XCTAssertNil(topics.first { $0.category == "quantum" }?.placement)

        // A category with no stored entry and no cards is unplaced with zero cards.
        let lab = topics.first { $0.category == "lab" }
        XCTAssertNil(lab?.placement)
        XCTAssertEqual(lab?.nCards, 0)
    }

    func testCheckItemsFollowBlueprintOrder() {
        let topics = Diagnostic.topics(stored: [:], nCards: [:])
        XCTAssertEqual(Diagnostic.checkItems(topics).map(\.category), Blueprint.slugs)
    }

    // MARK: Helpers

    private func placement(of placed: [PlacedTopic]) -> [String: DiagnosticPlacement] {
        Dictionary(uniqueKeysWithValues: placed.map { ($0.category, $0.placement) })
    }

    private func correctIndex(for category: String) -> Int {
        Diagnostic.quickChecks[category]!.answer
    }

    private func wrongIndex(for category: String) -> Int {
        let check = Diagnostic.quickChecks[category]!
        return (0..<check.choices.count).first { $0 != check.answer } ?? -1
    }
}
