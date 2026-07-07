// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Problem loading + rotation order for the Problems track, ported from the
// Problems door in pylib/anki/pgrep/study.py. The Problems door enforces the
// commit gate: the learner commits an answer BEFORE any help, which appends
// exactly one immutable Attempt (ladder_depth 0, the honest first-try signal).
//
// The static four-rung wrong-answer ladder that once followed a miss has been
// retired in favour of the gated decomposition tutor (DecompositionTutor.swift +
// SubproblemCardView.swift), which walks pre-generated subproblems one at a time
// and never reveals the parent answer. This file is kept for the pieces the
// interleaved study session still reuses: the item model (LadderProblem +
// LadderStep, read from a pgrep::Problem note) and the sitting order
// (LadderSession.arrange, study.py's rotation + PROBLEMS_PER_SESSION). The
// commit writes its Attempt through Engine.logAttempts / AttemptWriter.

import Foundation

/// One stored decomposition step (a sub-goal plus its rubric line). The
/// worked-solution reveal shown on a miss with no gated tutor walks these
/// (SolutionRevealView), and study.py stores them as `solution_decomposition`.
struct LadderStep: Sendable, Equatable {
    var subgoal: String
    var rubric: String
}

/// A problem for the Problems track: the exam item plus the stored teaching data
/// read from a `pgrep::Problem` note. The correct answer is carried so the phone
/// can grade the commit locally; the UI must not reveal it on a miss that opens
/// the gated tutor.
struct LadderProblem: Sendable, Equatable, Identifiable {
    var id: Int64 { noteId }
    var noteId: Int64
    var stem: String
    var choices: [String]
    var correctLetter: String
    var category: String
    var topic: String?
    var difficulty: Double?
    /// Letter -> short rationale for that distractor (never the correct letter).
    var rationales: [String: String]
    /// Ordered sub-goals + rubrics; the worked-solution reveal walks these.
    var decomposition: [LadderStep]
}

/// A bounded, rotating sitting of the seeded problems, mirroring study.py's
/// _problem_order + PROBLEMS_PER_SESSION: unseen items lead, then last-wrong,
/// then last-correct (least-recently touched first within a tier), round-robined
/// across categories in blueprint order so consecutive items differ in topic.
enum LadderSession {
    /// A sitting hands over a bounded batch, not the whole bank (study.PROBLEMS_PER_SESSION).
    static let problemsPerSession = 20

    /// Order the problems for a sitting and take the first `limit`.
    static func arrange(
        problems: [LadderProblem],
        lastByItem: [Int64: (correct: Bool, answeredAt: Int)],
        limit: Int = problemsPerSession
    ) -> [LadderProblem] {
        guard !problems.isEmpty else { return [] }

        var byCategory: [String: [LadderProblem]] = [:]
        for problem in problems {
            byCategory[problem.category, default: []].append(problem)
        }
        for key in byCategory.keys {
            byCategory[key]!.sort { rotationKey($0, lastByItem) < rotationKey($1, lastByItem) }
        }

        // Blueprint order first, then any off-blueprint categories, sorted.
        var ordered = Blueprint.slugs.filter { byCategory[$0] != nil }
        ordered += byCategory.keys.filter { !Blueprint.slugs.contains($0) }.sorted()

        var queues = byCategory
        var order: [LadderProblem] = []
        while order.count < limit {
            var progressed = false
            for category in ordered {
                guard order.count < limit else { break }
                if !(queues[category]?.isEmpty ?? true) {
                    order.append(queues[category]!.removeFirst())
                    progressed = true
                }
            }
            if !progressed { break }
        }
        return order
    }

    /// Sort key for one problem: unseen first (tier 0), then last-wrong (tier 1),
    /// then last-correct (tier 2); within a tier the oldest attempt leads, ties
    /// break on note id. Mirrors study._rotation_key. Lower sorts earlier.
    static func rotationKey(
        _ problem: LadderProblem,
        _ lastByItem: [Int64: (correct: Bool, answeredAt: Int)]
    ) -> (Int, Int, Int64) {
        guard let info = lastByItem[problem.noteId] else {
            return (0, 0, problem.noteId)
        }
        return (info.correct ? 2 : 1, info.answeredAt, problem.noteId)
    }
}
