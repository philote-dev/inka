// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// The wrong-answer ladder (productive failure), ported from
// pylib/anki/pgrep/study.py's Problems door. The Problems door enforces the
// commit gate: the learner commits an answer BEFORE any help, which appends
// exactly one immutable Attempt (ladder_depth 0, the honest first-try signal),
// then a static four-rung ladder built from the item's STORED
// solution_decomposition (nudge -> decompose -> sibling -> reveal). Because the
// decomposition ships with the item, the ladder is AI-off by construction:
// hint-time just walks the stored steps (reveal-and-self-compare). The final
// answer appears only in the reveal rung.
//
// This file is the pure, testable core (item model + session order + ladder
// construction); LadderView.swift is the SwiftUI surface, and the commit writes
// its Attempt through Engine.logAttempts / AttemptWriter.

import Foundation

/// One stored decomposition step (a sub-goal plus its rubric line).
struct LadderStep: Sendable, Equatable {
    var subgoal: String
    var rubric: String
}

/// A problem for the ladder: the exam item plus the stored teaching data the
/// ladder needs (distractor rationales + solution decomposition), read from a
/// `pgrep::Problem` note. The correct answer is carried so the phone can grade
/// the commit locally; the UI must not reveal it before the reveal rung.
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
    /// Ordered sub-goals + rubrics; the decompose/reveal rungs walk these.
    var decomposition: [LadderStep]
}

/// The four ladder rungs, in order. Prompts orient without leaking the answer;
/// only `reveal` shows the worked solution and the final answer.
enum LadderRungKind: String, Sendable {
    case nudge
    case decompose
    case sibling
    case reveal

    /// Human title shown on the rung (mirrors the desktop RUNG_TITLES map).
    var title: String {
        switch self {
        case .nudge: return "Nudge"
        case .decompose: return "Break it down"
        case .sibling: return "Sibling worked example"
        case .reveal: return "Reveal and explain back"
        }
    }
}

/// One built rung: a prompt always, and (for decompose/reveal) an HTML reveal
/// the learner opts into after trying it themselves.
struct LadderRung: Sendable, Equatable, Identifiable {
    var id: String { kind.rawValue }
    var kind: LadderRungKind
    var prompt: String
    /// HTML shown when the learner taps "Show" (nil for prompt-only rungs).
    var revealHTML: String?
}

/// The static ladder copy + builders, mirroring study.py (AI off). Copy follows
/// the project style: no em-dashes, light on colons.
enum Ladder {
    static let nudgePrompt =
        "Step back before you compute. What kind of problem is this, and which "
            + "principle applies? Name it in your own words first."
    static let decomposePrompt =
        "Break it into ordered sub-goals. Write each sub-goal and one line on why, "
            + "then show the stored steps and compare yours."
    static let siblingPrompt =
        "Try the same principle on a nearby case. Change one given, redo the "
            + "reasoning, and see whether your method still holds."
    static let revealPrompt =
        "Compare your work with the full solution, then say in one line where the trap was."

    /// Build the four-rung ladder from the stored decomposition, mirroring
    /// study._build_ladder. Nudge orients; decompose reveals the stored sub-goals
    /// (method only); sibling points at a near-transfer case; reveal shows the
    /// full worked solution, the one place the final answer appears.
    static func build(for problem: LadderProblem) -> [LadderRung] {
        let stepsHTML = decompositionHTML(problem.decomposition)
        let correctText = choiceText(problem.correctLetter, choices: problem.choices)
        return [
            LadderRung(kind: .nudge, prompt: nudgePrompt, revealHTML: nil),
            LadderRung(kind: .decompose, prompt: decomposePrompt, revealHTML: stepsHTML),
            LadderRung(kind: .sibling, prompt: siblingPrompt, revealHTML: nil),
            LadderRung(
                kind: .reveal,
                prompt: revealPrompt,
                revealHTML: revealHTML(
                    stepsHTML: stepsHTML,
                    correctLetter: problem.correctLetter,
                    correctText: correctText
                )
            ),
        ]
    }

    /// Feedback shown right after commit, mirroring study._rationale_html: a hold
    /// on a hit, the selected distractor's rationale on a miss, else a nudge.
    static func rationaleHTML(
        correct: Bool,
        selectedLetter: String,
        rationales: [String: String]
    ) -> String {
        if correct {
            return "<p>Correct. Hold onto the reasoning you used.</p>"
        }
        if let text = rationales[selectedLetter.uppercased()], !text.isEmpty {
            return "<p>\(text)</p>"
        }
        return "<p>Not quite. Work through the steps below.</p>"
    }

    // MARK: - HTML builders (mirror study.py)

    static func decompositionHTML(_ decomposition: [LadderStep]) -> String {
        guard !decomposition.isEmpty else {
            return "<p>No stored steps for this item.</p>"
        }
        let items = decomposition
            .map { "<li><strong>\($0.subgoal).</strong> \($0.rubric)</li>" }
            .joined()
        return "<ol>\(items)</ol>"
    }

    static func revealHTML(stepsHTML: String, correctLetter: String, correctText: String) -> String {
        let answerLine = correctText.isEmpty
            ? "<p class=\"answer\">Answer \(correctLetter).</p>"
            : "<p class=\"answer\">Answer \(correctLetter), \(correctText).</p>"
        return "\(stepsHTML)\n\(answerLine)"
    }

    static func choiceText(_ letter: String, choices: [String]) -> String {
        guard let scalar = letter.uppercased().unicodeScalars.first else { return "" }
        let index = Int(scalar.value) - Int(("A" as Unicode.Scalar).value)
        guard index >= 0, index < choices.count else { return "" }
        return choices[index]
    }
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
