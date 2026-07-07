// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// The interleaved study session (today's session), ported from the two-door
// study loop in pylib/anki/pgrep/study.py and the desktop launcher at
// ts/routes/pgrep/study/+page.svelte. The desktop keeps Cards and Problems as
// two separate doors (topics interleave within a door, never a card<->problem
// shuffle); on the phone the single "today's session" weaves the two tracks into
// one queue so the learner just taps Start and works through both.
//
// Faithful to study.py where the engine allows:
//   - Cards come from the real FSRS scheduler in points-at-stake order (the deck
//     config's selector), graded through the genuine answer loop (Engine.answer).
//   - Problems come from the seeded pgrep::Problem bank in study.py's rotation
//     order (unseen first, then last-wrong, then last-correct; round-robined
//     across categories, capped at PROBLEMS_PER_SESSION). That order + cap are
//     already ported in LadderSession.arrange, which the session reuses.
//   - The Problems commit gate holds: a learner commits BEFORE any help, which
//     appends exactly one immutable Attempt (ladder_depth 0). A hit affirms the
//     picked answer; a miss reveals the correct choice and the stored worked
//     solution (study.commit_problem's no-decomposition branch). The richer
//     gated decomposition tutor is the next task; `revealSteps` marks the seam.
//
// This file is the pure, testable core (no SwiftUI, no engine): the interleave
// order and the commit grading. StudySessionView.swift drives it against the
// shared Engine, mirroring the ChoiceList/ChoiceListView and Ladder/LadderView
// split so the host-less test bundle can exercise the logic.

import Foundation

/// One item in the interleaved queue: a memory card or a performance problem.
enum StudyItemKind: Equatable {
    case card
    case problem
}

/// Pure interleaving + grading for the interleaved study session. Namespaced
/// (no state) so the host-less test bundle can pin the order and the commit
/// resolution without a running app or engine.
enum StudySession {
    /// A sitting hands over a bounded batch of problems, not the whole bank,
    /// matching study.PROBLEMS_PER_SESSION. Kept in step with
    /// LadderSession.problemsPerSession (the loader the session reuses); a plain
    /// literal here so the pure core needs no other file in the test bundle.
    static let problemsPerSession = 20

    /// Choose the next item, weaving the two tracks evenly. Cards lead on a tie
    /// so memory primes the problems (the desktop's "retrieval that primes the
    /// problems" framing). Returns `nil` once both tracks are exhausted.
    ///
    /// Both tracks live: serve whichever is further behind its own share, using
    /// each track's next-item midpoint `(served + 0.5) / total`. `cardsRemaining`
    /// is the scheduler's live queue count (it includes the card on offer), so
    /// `servedCards + cardsRemaining` estimates the card total even as an Again
    /// requeues; the estimate only nudges the weave and never strands an item.
    static func nextKind(
        cardsAvailable: Bool,
        cardsRemaining: Int,
        servedCards: Int,
        problemsRemaining: Int,
        servedProblems: Int
    ) -> StudyItemKind? {
        let haveProblem = problemsRemaining > 0
        if !cardsAvailable && !haveProblem { return nil }
        if !haveProblem { return .card }
        if !cardsAvailable { return .problem }

        let totalCards = max(servedCards + cardsRemaining, 1)
        let totalProblems = max(servedProblems + problemsRemaining, 1)
        let cardMidpoint = (Double(servedCards) + 0.5) / Double(totalCards)
        let problemMidpoint = (Double(servedProblems) + 0.5) / Double(totalProblems)
        return cardMidpoint <= problemMidpoint ? .card : .problem
    }

    /// The full interleave order for a static sitting (`cards` due cards and
    /// `problems` queued problems), by walking `nextKind` with the counts drawn
    /// down each step. Deterministic, so it pins the weave in tests; the live
    /// session uses `nextKind` directly against the scheduler's changing counts.
    static func plan(cards: Int, problems: Int) -> [StudyItemKind] {
        var order: [StudyItemKind] = []
        var servedCards = 0
        var servedProblems = 0
        while true {
            let kind = nextKind(
                cardsAvailable: servedCards < cards,
                cardsRemaining: cards - servedCards,
                servedCards: servedCards,
                problemsRemaining: problems - servedProblems,
                servedProblems: servedProblems
            )
            guard let kind else { break }
            order.append(kind)
            if kind == .card { servedCards += 1 } else { servedProblems += 1 }
        }
        return order
    }

    /// Grade a committed problem answer against its correct letter, case- and
    /// whitespace-insensitive. An empty pick is never correct. Mirrors the
    /// comparison in study.commit_problem.
    static func isCorrect(selected: String, correctLetter: String) -> Bool {
        let picked = selected.trimmingCharacters(in: .whitespaces).uppercased()
        let key = correctLetter.trimmingCharacters(in: .whitespaces).uppercased()
        return !picked.isEmpty && picked == key
    }

    /// The worked-solution steps to reveal after a commit: none on a hit (the
    /// affirmed correct choice is enough), the stored steps on a miss so the
    /// learner leaves with the idea instead of a dead end (study.commit_problem's
    /// no-decomposition branch, via decomposition.parent_explanation).
    ///
    /// This is the tutor seam: when a missed problem carries decomposition-tutor
    /// data, the next task branches here to open the gated tutor instead of this
    /// static reveal. Generic over the step type so the pure core stays free of
    /// the LadderStep model and the test bundle needs only this one file.
    static func revealSteps<Step>(correct: Bool, solutionSteps: [Step]) -> [Step] {
        correct ? [] : solutionSteps
    }
}
