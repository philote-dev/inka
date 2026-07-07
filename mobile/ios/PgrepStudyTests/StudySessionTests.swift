// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Pins the interleaved study session's pure core (StudySession): the card /
// problem weave (nextKind + plan), the next-item transitions as a track drains,
// and the commit hit/miss resolution (grading + the miss-only worked-solution
// reveal). The SwiftUI model/view that drives this against the engine is not
// unit-tested here, matching how ChoiceList's logic is pinned while its view is
// left to the app target. Deterministic by construction: pure functions only.

import XCTest

final class StudySessionTests: XCTestCase {
    // MARK: Interleave order (plan)

    func testPlanAllCardsWhenNoProblems() {
        XCTAssertEqual(StudySession.plan(cards: 3, problems: 0), [.card, .card, .card])
    }

    func testPlanAllProblemsWhenNoCards() {
        XCTAssertEqual(StudySession.plan(cards: 0, problems: 3), [.problem, .problem, .problem])
    }

    func testPlanEmptyWhenNothingDue() {
        XCTAssertEqual(StudySession.plan(cards: 0, problems: 0), [])
    }

    func testPlanLeadsWithCardOnATie() {
        // Memory primes the problems, so a card leads when the two are even.
        XCTAssertEqual(StudySession.plan(cards: 1, problems: 1), [.card, .problem])
    }

    func testPlanAlternatesWhenBalanced() {
        XCTAssertEqual(
            StudySession.plan(cards: 2, problems: 2),
            [.card, .problem, .card, .problem]
        )
        XCTAssertEqual(
            StudySession.plan(cards: 3, problems: 3),
            [.card, .problem, .card, .problem, .card, .problem]
        )
    }

    func testPlanSpacesTheSmallerTrackEvenly() {
        // Six cards, three problems: a problem lands about every third item, and
        // the two are never clumped (cards outnumber problems).
        XCTAssertEqual(
            StudySession.plan(cards: 6, problems: 3),
            [.card, .problem, .card, .card, .problem, .card, .card, .problem, .card]
        )
        XCTAssertFalse(hasAdjacentProblems(StudySession.plan(cards: 6, problems: 3)))
    }

    func testPlanPreservesEachTrackCount() {
        for (cards, problems) in [(6, 3), (5, 20), (20, 5), (7, 7), (1, 4), (13, 2)] {
            let order = StudySession.plan(cards: cards, problems: problems)
            XCTAssertEqual(order.filter { $0 == .card }.count, cards, "cards for (\(cards), \(problems))")
            XCTAssertEqual(order.filter { $0 == .problem }.count, problems, "problems for (\(cards), \(problems))")
            XCTAssertEqual(order.count, cards + problems, "total for (\(cards), \(problems))")
        }
    }

    // MARK: Next-item transitions (nextKind)

    func testNextKindNilWhenBothExhausted() {
        XCTAssertNil(StudySession.nextKind(
            cardsAvailable: false, cardsRemaining: 0,
            servedCards: 4, problemsRemaining: 0, servedProblems: 3
        ))
    }

    func testNextKindServesRemainingCardsWhenProblemsDone() {
        XCTAssertEqual(
            StudySession.nextKind(
                cardsAvailable: true, cardsRemaining: 3,
                servedCards: 2, problemsRemaining: 0, servedProblems: 5
            ),
            .card
        )
    }

    func testNextKindServesRemainingProblemsWhenCardsDone() {
        XCTAssertEqual(
            StudySession.nextKind(
                cardsAvailable: false, cardsRemaining: 0,
                servedCards: 6, problemsRemaining: 2, servedProblems: 1
            ),
            .problem
        )
    }

    func testNextKindLeadsWithCardOnATie() {
        XCTAssertEqual(
            StudySession.nextKind(
                cardsAvailable: true, cardsRemaining: 2,
                servedCards: 0, problemsRemaining: 2, servedProblems: 0
            ),
            .card
        )
    }

    func testNextKindPicksTheTrackFurtherBehind() {
        // A card was just served (1 of 6 done); the problem track has served
        // none of 3, so it is further behind and comes next.
        XCTAssertEqual(
            StudySession.nextKind(
                cardsAvailable: true, cardsRemaining: 5,
                servedCards: 1, problemsRemaining: 3, servedProblems: 0
            ),
            .problem
        )
        // Symmetric: with a problem already served and cards untouched, a card
        // is further behind.
        XCTAssertEqual(
            StudySession.nextKind(
                cardsAvailable: true, cardsRemaining: 6,
                servedCards: 0, problemsRemaining: 2, servedProblems: 1
            ),
            .card
        )
    }

    // MARK: Commit hit / miss resolution

    func testIsCorrectMatchesLetterCaseAndWhitespaceInsensitively() {
        XCTAssertTrue(StudySession.isCorrect(selected: "B", correctLetter: "B"))
        XCTAssertTrue(StudySession.isCorrect(selected: "b", correctLetter: " B "))
        XCTAssertTrue(StudySession.isCorrect(selected: " c ", correctLetter: "C"))
    }

    func testIsCorrectRejectsWrongOrEmptyPick() {
        XCTAssertFalse(StudySession.isCorrect(selected: "A", correctLetter: "B"))
        XCTAssertFalse(StudySession.isCorrect(selected: "", correctLetter: "B"))
        XCTAssertFalse(StudySession.isCorrect(selected: "   ", correctLetter: "B"))
    }

    func testRevealStepsHiddenOnHitShownOnMiss() {
        let steps = ["name the principle", "set up the equation", "solve"]
        // A hit needs no reveal (the affirmed correct choice is enough).
        XCTAssertEqual(StudySession.revealSteps(correct: true, solutionSteps: steps), [])
        // A miss reveals the stored worked solution, in order.
        XCTAssertEqual(StudySession.revealSteps(correct: false, solutionSteps: steps), steps)
    }

    // MARK: Constants

    func testProblemsPerSessionMatchesDesktopCap() {
        XCTAssertEqual(StudySession.problemsPerSession, 20)
    }

    // MARK: Helpers

    private func hasAdjacentProblems(_ order: [StudyItemKind]) -> Bool {
        for i in 1..<max(order.count, 1) where order[i] == .problem && order[i - 1] == .problem {
            return true
        }
        return false
    }
}
