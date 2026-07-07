// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Pins the gated decomposition tutor's pure core (DecompositionTutor): parsing
// the stored decomposition_tutor blob into usable subproblems (dropping
// malformed variants), deterministic variant selection by round, the withheld
// load view, and the MCQ grade (correct / incorrect / out-of-range), mirroring
// pylib/anki/pgrep/decomposition.py (load_tutor, check_mcq, _variant,
// _usable_subproblems, _valid_variant, has_tutor). AI off, so the explain gate
// stays skipped (needs_explanation follows the aiEnabled flag). The SwiftUI card
// (SubproblemCardView) and the Engine read (Engine.loadTutor) are left to the app
// target, matching how ChoiceList's logic is pinned while its view is not.

import XCTest

final class DecompositionTutorTests: XCTestCase {
    // A tutor with two usable subproblems. Subproblem 0 carries two valid
    // variants (so round selection can be pinned); subproblem 1 carries one valid
    // variant plus one malformed (four choices) that parsing must drop. One key
    // is lowercase ("c") to prove keys are uppercased. A parent variant is
    // included to prove parent_variants are parsed.
    private let fixture = """
    {
      "subproblems": [
        {
          "prompt": "P0",
          "variants": [
            {
              "stem": "S0V0",
              "choices": ["a0", "b0", "c0", "d0", "e0"],
              "key": "A",
              "distractor_rationales": {"B": "r0b", "C": "r0c"},
              "explain_why": "why0v0",
              "source_ref": "src0v0"
            },
            {
              "stem": "S0V1",
              "choices": ["a1", "b1", "c1", "d1", "e1"],
              "key": "c",
              "distractor_rationales": {"A": "r1a"},
              "explain_why": "why0v1"
            }
          ]
        },
        {
          "prompt": "P1",
          "variants": [
            {
              "stem": "S1V0",
              "choices": ["x0", "x1", "x2", "x3", "x4"],
              "key": "B",
              "explain_why": "why1v0"
            },
            {
              "stem": "S1BAD",
              "choices": ["only", "four", "choices", "here"],
              "key": "A"
            }
          ]
        }
      ],
      "parent_variants": [
        {"stem": "PARENT", "choices": ["p0", "p1", "p2", "p3", "p4"], "key": "d"}
      ]
    }
    """

    private func parsedFixture() -> DecompositionTutor {
        DecompositionTutor.parse(json: fixture)
    }

    // MARK: Parsing + usable subproblems

    func testParseKeepsUsableSubproblemsInOrderDroppingBadVariants() {
        let tutor = parsedFixture()
        XCTAssertTrue(tutor.hasTutor)
        XCTAssertEqual(tutor.count, 2)
        XCTAssertEqual(tutor.subproblems[0].prompt, "P0")
        XCTAssertEqual(tutor.subproblems[1].prompt, "P1")
        // Subproblem 0 keeps both valid variants; subproblem 1 drops the
        // four-choice variant, keeping only the well-formed one.
        XCTAssertEqual(tutor.subproblems[0].variants.count, 2)
        XCTAssertEqual(tutor.subproblems[1].variants.count, 1)
        // Keys are uppercased ("c" -> "C").
        XCTAssertEqual(tutor.subproblems[0].variants[1].key, "C")
    }

    func testParentVariantsParsedAndKeyUppercased() {
        let tutor = parsedFixture()
        XCTAssertEqual(tutor.parentVariants.count, 1)
        XCTAssertEqual(tutor.parentVariants.first?.key, "D")
        XCTAssertEqual(tutor.parentVariants.first?.stem, "PARENT")
    }

    // MARK: has_tutor true / false

    func testHasTutorFalseForEmptyOrMalformedBlob() {
        for blob in ["{}", "", "not json", "[]", "{\"subproblems\": []}"] {
            let tutor = DecompositionTutor.parse(json: blob)
            XCTAssertFalse(tutor.hasTutor, "expected no tutor for \(blob.isEmpty ? "<empty>" : blob)")
            XCTAssertEqual(tutor.count, 0)
        }
    }

    func testHasTutorFalseWhenEverySubproblemVariantIsInvalid() {
        // One four-choice variant and one out-of-range key: both invalid, so the
        // subproblem is not usable and the tutor has nothing to run.
        let blob = """
        {"subproblems": [{"prompt": "bad", "variants": [
          {"stem": "x", "choices": ["a", "b", "c", "d"], "key": "A"},
          {"stem": "y", "choices": ["a", "b", "c", "d", "e"], "key": "F"}
        ]}]}
        """
        let tutor = DecompositionTutor.parse(json: blob)
        XCTAssertFalse(tutor.hasTutor)
        XCTAssertEqual(tutor.count, 0)
    }

    // MARK: load (answers + help withheld) and deterministic variant selection

    func testLoadReturnsStemsAndChoicesForEachSubproblem() {
        let steps = parsedFixture().load(roundIndex: 0)
        XCTAssertEqual(steps.count, 2)
        XCTAssertEqual(steps[0].index, 0)
        XCTAssertEqual(steps[0].variantIndex, 0)
        XCTAssertEqual(steps[0].prompt, "P0")
        XCTAssertEqual(steps[0].stemHtml, "S0V0")
        XCTAssertEqual(steps[0].choices, ["a0", "b0", "c0", "d0", "e0"])
        XCTAssertEqual(steps[1].index, 1)
        XCTAssertEqual(steps[1].stemHtml, "S1V0")
    }

    func testVariantSelectionIsDeterministicAndWrapsByRound() {
        let tutor = parsedFixture()
        // Round 0: the first variant of each subproblem.
        XCTAssertEqual(tutor.load(roundIndex: 0).map(\.stemHtml), ["S0V0", "S1V0"])
        // Round 1: subproblem 0 advances to its second variant; subproblem 1 has
        // only one, so it wraps back to it.
        let round1 = tutor.load(roundIndex: 1)
        XCTAssertEqual(round1.map(\.stemHtml), ["S0V1", "S1V0"])
        XCTAssertEqual(round1[0].variantIndex, 1)
        XCTAssertEqual(round1[1].variantIndex, 0)
        // Round 2: subproblem 0 (two variants) wraps back to the first.
        XCTAssertEqual(tutor.load(roundIndex: 2).map(\.stemHtml), ["S0V0", "S1V0"])
        // Same round always yields the same numbers (deterministic).
        XCTAssertEqual(tutor.load(roundIndex: 0), tutor.load(roundIndex: 0))
    }

    // MARK: MCQ grading (correct)

    func testCheckMcqCorrectRevealsRationaleAndFollowsAiFlag() {
        let tutor = parsedFixture()
        guard case let .correct(key, why, needsExplanation)? = tutor.checkMcq(
            subgoalIndex: 0, variantIndex: 0, selected: "A"
        ) else {
            return XCTFail("expected a correct outcome for the served key")
        }
        XCTAssertEqual(key, "A")
        XCTAssertEqual(why, "why0v0")
        // AI off (default): the explain gate is skipped.
        XCTAssertFalse(needsExplanation)

        // With AI on, the explain gate would apply (needs_explanation = ai_enabled).
        guard case let .correct(_, _, needsWithAi)? = tutor.checkMcq(
            subgoalIndex: 0, variantIndex: 0, selected: "A", aiEnabled: true
        ) else {
            return XCTFail("expected a correct outcome with AI on")
        }
        XCTAssertTrue(needsWithAi)
    }

    func testCheckMcqCorrectIsCaseAndWhitespaceInsensitive() {
        let tutor = parsedFixture()
        guard case .correct? = tutor.checkMcq(subgoalIndex: 0, variantIndex: 0, selected: "  a ") else {
            return XCTFail("a lowercase, padded pick of the key should be correct")
        }
    }

    // MARK: MCQ grading (incorrect: distractor rationale, key withheld)

    func testCheckMcqIncorrectReturnsThatDistractorRationale() {
        let tutor = parsedFixture()
        guard case let .incorrect(rationale)? = tutor.checkMcq(
            subgoalIndex: 0, variantIndex: 0, selected: "B"
        ) else {
            return XCTFail("expected an incorrect outcome for a wrong pick")
        }
        XCTAssertEqual(rationale, "r0b")
    }

    func testCheckMcqIncorrectWithNoStoredRationaleIsEmpty() {
        let tutor = parsedFixture()
        // "D" is wrong and has no stored rationale -> empty string (never the key).
        guard case let .incorrect(rationale)? = tutor.checkMcq(
            subgoalIndex: 0, variantIndex: 0, selected: "D"
        ) else {
            return XCTFail("expected an incorrect outcome")
        }
        XCTAssertEqual(rationale, "")
    }

    func testCheckMcqEmptyPickIsIncorrect() {
        let tutor = parsedFixture()
        guard case .incorrect? = tutor.checkMcq(subgoalIndex: 0, variantIndex: 0, selected: "") else {
            return XCTFail("an empty pick is never correct")
        }
    }

    func testCheckMcqGradesAgainstTheServedVariantNotTheFirst() {
        let tutor = parsedFixture()
        // Subproblem 0, variant 1 has key "C". The variant-0 key "A" is now a
        // distractor and returns variant 1's rationale for it.
        guard case .correct? = tutor.checkMcq(subgoalIndex: 0, variantIndex: 1, selected: "C") else {
            return XCTFail("variant 1's key is C")
        }
        guard case let .incorrect(rationale)? = tutor.checkMcq(
            subgoalIndex: 0, variantIndex: 1, selected: "A"
        ) else {
            return XCTFail("A is a distractor in variant 1")
        }
        XCTAssertEqual(rationale, "r1a")
    }

    // MARK: Variant range + out-of-range subproblem

    func testVariantIndexWrapsModuloVariantCount() {
        let tutor = parsedFixture()
        // Subproblem 0 has two variants: index 2 wraps to 0, index 3 wraps to 1.
        XCTAssertEqual(tutor.variant(subgoalIndex: 0, variantIndex: 2)?.stem, "S0V0")
        XCTAssertEqual(tutor.variant(subgoalIndex: 0, variantIndex: 3)?.stem, "S0V1")
    }

    func testCheckMcqOutOfRangeSubproblemReturnsNil() {
        let tutor = parsedFixture()
        XCTAssertNil(tutor.checkMcq(subgoalIndex: 5, variantIndex: 0, selected: "A"))
        XCTAssertNil(tutor.checkMcq(subgoalIndex: -1, variantIndex: 0, selected: "A"))
        XCTAssertNil(tutor.variant(subgoalIndex: 9, variantIndex: 0))
    }
}

/// End-to-end proof against the shipped seed: the bundled sample deck's
/// pgrep::Problem notes really carry well-formed decomposition_tutor data at the
/// expected field, so DecompositionTutor.parse (and Engine.loadTutor, which reads
/// the same field) drives the tutor on a real miss. Opens the shared engine like
/// EngineSmokeTests; needs only AnkiBackend + StudySandbox (both in this bundle).
final class DecompositionTutorSeedTests: XCTestCase {
    // Field 7 of pgrep::Problem is decomposition_tutor (problem.py field order),
    // mirrored by ProblemNote.decompositionTutorIndex in the app target.
    private let decompositionTutorIndex = 7
    // The seed marker tag on every bundled problem (problem.PROBLEM_SEED_TAG).
    private let seedSearch = "tag:pgrep::problem-seed"

    func testSeededProblemsCarryUsableTutorData() throws {
        let backend = try AnkiBackend()
        let bundle = Bundle(for: Self.self)
        guard let deckURL = StudySandbox.bundledDeckURL(in: bundle) else {
            return XCTFail("bundled collection.anki2 not found in the test bundle")
        }
        let sandbox = FileManager.default.temporaryDirectory
            .appendingPathComponent("PgrepTutorTests-\(UUID().uuidString)", isDirectory: true)
        let staged = try StudySandbox.stage(from: deckURL, in: sandbox, freshCopy: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: sandbox) }
        try backend.openCollection(path: staged.collectionPath, mediaFolder: staged.mediaFolderPath)
        addTeardownBlock { try? backend.closeCollection() }

        let noteIds = try backend.searchNotes(matching: seedSearch)
        XCTAssertGreaterThan(noteIds.count, 0, "the seeded deck should contain problems")

        var withTutor = 0
        var validatedOne = false
        for nid in noteIds {
            let note = try backend.getNote(noteId: nid)
            guard note.fields.count > decompositionTutorIndex else { continue }
            let tutor = DecompositionTutor.parse(json: note.fields[decompositionTutorIndex])
            guard tutor.hasTutor else { continue }
            withTutor += 1
            guard !validatedOne else { continue }
            validatedOne = true
            // Every served step withholds the answer but carries a five-choice MCQ.
            let steps = tutor.load(roundIndex: 0)
            XCTAssertEqual(steps.count, tutor.count)
            for step in steps {
                XCTAssertEqual(step.choices.count, 5, "each subproblem variant has five choices")
            }
            // The first step grades an obvious miss (an empty pick) as incorrect.
            let first = steps[0]
            guard case .incorrect? = tutor.checkMcq(
                subgoalIndex: first.index, variantIndex: first.variantIndex, selected: ""
            ) else {
                return XCTFail("an empty pick should grade as incorrect")
            }
        }
        XCTAssertGreaterThan(withTutor, 0, "at least one seeded problem should carry a usable tutor")
    }
}
