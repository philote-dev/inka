// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Pins the shared choice list's pure logic: the A..E letter labeling and the
// pre/post-commit row-state resolution ported from ChoiceList.svelte. The honesty
// rule (a wrong pick is `wrong`, resolved neutrally, never a correct/affirmed
// state) is asserted here; the SwiftUI rendering is not unit-tested.

import XCTest

final class ChoiceListTests: XCTestCase {
    // MARK: Letter labeling

    func testLetterLabelsAtoE() {
        XCTAssertEqual(ChoiceList.letter(for: 0), "A")
        XCTAssertEqual(ChoiceList.letter(for: 1), "B")
        XCTAssertEqual(ChoiceList.letter(for: 2), "C")
        XCTAssertEqual(ChoiceList.letter(for: 3), "D")
        XCTAssertEqual(ChoiceList.letter(for: 4), "E")
    }

    func testLetterLabelsWrapPastZ() {
        XCTAssertEqual(ChoiceList.letter(for: 25), "Z")
        XCTAssertEqual(ChoiceList.letter(for: 26), "AA")
        XCTAssertEqual(ChoiceList.letter(for: 27), "AB")
    }

    func testLetterLabelNegativeIsPlaceholder() {
        XCTAssertEqual(ChoiceList.letter(for: -1), "?")
    }

    func testLetteredAssignsLettersInOrder() {
        let options = ChoiceList.lettered(["one", "two", "three", "four", "five"])
        // Matches examChoiceLetters (["A", "B", "C", "D", "E"]) so lettered() is a
        // drop-in for the existing exam/ladder choice labeling.
        XCTAssertEqual(options.map(\.key), ["A", "B", "C", "D", "E"])
        XCTAssertEqual(options.map(\.html), ["one", "two", "three", "four", "five"])
    }

    // MARK: Pre-commit state

    func testPreCommitSelectionHighlightsOnlyThePick() {
        XCTAssertEqual(
            ChoiceList.rowState(key: "B", selected: "B", committed: false, correctKey: nil),
            .selected
        )
        XCTAssertEqual(
            ChoiceList.rowState(key: "A", selected: "B", committed: false, correctKey: nil),
            .normal
        )
    }

    func testPreCommitNoSelectionIsAllNormal() {
        for key in ["A", "B", "C"] {
            XCTAssertEqual(
                ChoiceList.rowState(key: key, selected: nil, committed: false, correctKey: nil),
                .normal
            )
        }
    }

    // MARK: Post-commit reveal

    func testCommittedCorrectPickIsAffirmedNotMarkedWrong() {
        // The learner picked the right answer: the answer reveal wins, so the row
        // is `correct` (affirmed), never `wrong`.
        XCTAssertEqual(
            ChoiceList.rowState(key: "C", selected: "C", committed: true, correctKey: "C"),
            .correct
        )
    }

    func testCommittedWrongPickIsNeutralWrongAndCorrectIsAffirmed() {
        // Picked D, answer is B. B is `correct`; D is `wrong` (shown neutrally,
        // never red); the untouched choices are `locked`.
        XCTAssertEqual(
            ChoiceList.rowState(key: "B", selected: "D", committed: true, correctKey: "B"),
            .correct
        )
        XCTAssertEqual(
            ChoiceList.rowState(key: "D", selected: "D", committed: true, correctKey: "B"),
            .wrong
        )
        XCTAssertEqual(
            ChoiceList.rowState(key: "A", selected: "D", committed: true, correctKey: "B"),
            .locked
        )
    }

    func testCommittedWithoutCorrectKeyStillLocksAndMarksThePick() {
        // No revealed answer (correctKey nil): the pick is `wrong` (the neutral
        // committed marker), the rest `locked`. Nothing is ever affirmed as
        // correct without an answer to affirm.
        XCTAssertEqual(
            ChoiceList.rowState(key: "A", selected: "A", committed: true, correctKey: nil),
            .wrong
        )
        XCTAssertEqual(
            ChoiceList.rowState(key: "B", selected: "A", committed: true, correctKey: nil),
            .locked
        )
    }
}
