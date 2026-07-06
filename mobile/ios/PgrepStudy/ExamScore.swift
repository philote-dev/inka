// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Timed Exam mode data + math for the iOS companion, ported from
// pylib/anki/pgrep/exam.py. Exam mode is the readiness-measuring instrument: a
// timed run of the seeded Problems under exam conditions, zero help, scored on
// the raw-to-scaled Readiness map. This file is the pure, testable core:
//   - ExamProblem, the item model read from the collection;
//   - ExamAssembly, the blueprint-weighted, anti-blocking run assembler
//     (assemble_exam + _allocate);
//   - ExamScore, which turns the session's answers into a projected scaled score
//     with an 80% range (exam_result), using the SAME readiness projection the
//     desktop uses (ReadinessTable.projectScaledScore) with a per-topic
//     Jeffreys-Beta estimate that stays honest at 0 and 1.
//
// Honesty note: this iOS build SCORES an exam in memory but does not yet WRITE
// the resulting Attempt notes back to the collection (that needs the note-add +
// notetype-bootstrap write path over FFI, a follow-up). So an exam here reports
// its own result honestly, but does not yet feed Home's Performance/Readiness.
// TODO: append clean Attempts on finish (exam.finish_exam) once the FFI write
// path lands, closing the loop so a phone exam lights up the three scores.

import Foundation

/// The choice letters a Problem may use, in order (problem.CHOICE_LETTERS).
let examChoiceLetters: [String] = ["A", "B", "C", "D", "E"]

/// Field schema for the desktop `pgrep::Problem` notetype (problem.py). Read-only
/// here; duplicated across the language boundary on purpose.
enum ProblemNote {
    static let notetypeName = "pgrep::Problem"
    /// The seed marker tag on every bundled problem (problem.PROBLEM_SEED_TAG).
    static let seedTag = "pgrep::problem-seed"
    /// Anki search for the problem bank. Uses the seed tag (the same pattern the
    /// desktop uses to find seeded problems), so it returns empty without error
    /// on a collection that has none. AI-generated problems that lack this tag
    /// are out of scope for the mobile exam bank.
    static let search = "tag:\(seedTag)"
    // Field order: stem, choices, correct, distractor_rationales,
    // solution_decomposition, difficulty, source_ref.
    static let stemIndex = 0
    static let choicesIndex = 1
    static let correctIndex = 2
    static let difficultyIndex = 5

    /// Parse the `choices` JSON array field into a list of strings.
    static func parseChoices(_ raw: String) -> [String] {
        guard let data = raw.data(using: .utf8),
              let array = try? JSONSerialization.jsonObject(with: data) as? [Any]
        else { return [] }
        return array.map { element in
            if let string = element as? String { return string }
            return String(describing: element)
        }
    }

    /// Parse the authored difficulty field ("3.00") to the 1..5 scale, or nil.
    static func parseDifficulty(_ raw: String) -> Double? {
        let trimmed = raw.trimmingCharacters(in: .whitespaces)
        guard let value = Double(trimmed) else { return nil }
        return min(max(value, 1.0), 5.0)
    }
}

/// One exam problem, read from a `pgrep::Problem` note. The correct answer is
/// carried so the phone can score locally; the UI must never reveal it before
/// the exam finishes (blind review).
struct ExamProblem: Sendable, Equatable, Identifiable {
    var id: Int64 { noteId }
    var noteId: Int64
    var stem: String
    var choices: [String]
    var correctLetter: String
    var category: String
    var difficulty: Double?
}

// MARK: - Assembly (blueprint-weighted, anti-blocking, no repeats)

enum ExamAssembly {
    /// The real PGRE is 100 scored questions; a section run is shorter.
    static let fullLengthQuestionCount = ReadinessTable.scoredQuestionCount
    static let defaultSectionQuestionCount = 20
    /// 170 minutes over 100 questions; pace scales with the run length.
    static let secondsPerQuestion = Double(170 * 60) / Double(ReadinessTable.scoredQuestionCount)

    /// Assemble a timed run of problems at real PGRE proportions. Allocates the
    /// count across categories by blueprint weight (largest remainder, capped by
    /// availability), then round-robins in blueprint order so consecutive items
    /// differ in topic (anti-blocking). A line-for-line port of assemble_exam.
    static func assemble(problems: [ExamProblem], questionCount: Int) -> [ExamProblem] {
        guard questionCount > 0, !problems.isEmpty else { return [] }

        var byCategory: [String: [ExamProblem]] = [:]
        for problem in problems {
            byCategory[problem.category, default: []].append(problem)
        }
        for key in byCategory.keys {
            byCategory[key]!.sort { $0.noteId < $1.noteId }
        }

        let ordered = orderedCategories(Array(byCategory.keys))
        var available: [String: Int] = [:]
        for category in ordered { available[category] = byCategory[category]!.count }
        let allocation = allocate(target: questionCount, ordered: ordered, available: available)

        var queues = byCategory
        var remaining = allocation
        var order: [ExamProblem] = []
        while remaining.values.reduce(0, +) > 0 {
            var progressed = false
            for category in ordered {
                if (remaining[category] ?? 0) > 0, !(queues[category]?.isEmpty ?? true) {
                    order.append(queues[category]!.removeFirst())
                    remaining[category]! -= 1
                    progressed = true
                }
            }
            if !progressed { break }
        }
        return order
    }

    /// Blueprint order first, then any off-blueprint categories, sorted.
    static func orderedCategories(_ categories: [String]) -> [String] {
        var out = Blueprint.slugs.filter { categories.contains($0) }
        out += categories.filter { !Blueprint.slugs.contains($0) }.sorted()
        return out
    }

    /// Blueprint-proportional counts per category, capped by availability
    /// (largest-remainder apportionment). Port of exam._allocate.
    static func allocate(target: Int, ordered: [String], available: [String: Int]) -> [String: Int] {
        let capacity = available.values.reduce(0, +)
        let target = min(target, capacity)
        var alloc: [String: Int] = [:]
        for category in ordered { alloc[category] = 0 }
        if target <= 0 { return alloc }

        let totalWeight = ordered.reduce(0.0) { $0 + (Blueprint.byCategory[$1] ?? 0.0) }
        var quotas: [String: Double] = [:]
        if totalWeight <= 0.0 {
            for category in ordered { quotas[category] = Double(target) / Double(ordered.count) }
        } else {
            for category in ordered {
                quotas[category] = (Blueprint.byCategory[category] ?? 0.0) / totalWeight * Double(target)
            }
        }

        for category in ordered {
            alloc[category] = min(available[category] ?? 0, Int(quotas[category]!))
        }
        var assigned = alloc.values.reduce(0, +)

        let byRemainder = ordered.sorted {
            (quotas[$0]! - Double(Int(quotas[$0]!))) > (quotas[$1]! - Double(Int(quotas[$1]!)))
        }
        while assigned < target {
            var progressed = false
            for category in byRemainder {
                if assigned >= target { break }
                if alloc[category]! < (available[category] ?? 0) {
                    alloc[category]! += 1
                    assigned += 1
                    progressed = true
                }
            }
            if !progressed { break }
        }
        return alloc
    }
}

// MARK: - Scoring (projected scaled + range, honest abstain)

/// Per-topic exam result row (exam.by_topic entries).
struct ExamTopicResult: Sendable, Equatable, Identifiable {
    var id: String { category }
    var category: String
    var blueprint: Double
    var nExam: Int
    var correct: Int
    var p: Double
    var pSD: Double
    var tested: Bool
}

/// The scored exam outcome (exam.exam_result). The scaled/low/high/raw are nil
/// when the exam abstains (no answers, or below the coverage gate); the raw
/// actual result and accuracy always report.
struct ExamResult: Sendable, Equatable {
    var total: Int
    var nAnswered: Int
    var correct: Int
    var incorrect: Int
    var skipped: Int
    var accuracy: Double
    var rawActual: Int
    var coveragePct: Double
    var coverageGate: Double
    var scaled: Int?
    var low: Int?
    var high: Int?
    var raw: Int?
    var expectedCorrect: Double?
    var abstain: Bool
    var reason: String?
    var byTopic: [ExamTopicResult]
    var testedTopics: [String]
    var untestedTopics: [String]
}

enum ExamScore {
    /// A topic counts as tested once it has at least this many answered questions.
    static let minTopicQuestions = 1
    static let reasonNoAnswers = "No answers recorded yet"
    static let reasonAbstain = "Not enough of the exam is covered yet"

    /// Score a finished exam from its answered items. `answered` is one
    /// (category, correct) per answered question; `served` is how many were
    /// presented (so skipped = served - answered). Port of exam_result +
    /// _topic_contributions, reusing the readiness projection.
    static func score(
        answered: [(category: String, correct: Bool)],
        served: Int,
        coverageGate: Double = CoverageScore.gate,
        guessBaseline: Double = ReadinessScore.guessBaseline
    ) -> ExamResult {
        let nAnswered = answered.count
        let correct = answered.reduce(0) { $0 + ($1.correct ? 1 : 0) }
        let incorrect = nAnswered - correct
        let skipped = max(0, served - nAnswered)
        let accuracy = nAnswered > 0 ? Double(correct) / Double(nAnswered) : 0.0

        var counts: [String: (correct: Int, total: Int)] = [:]
        for item in answered {
            var entry = counts[item.category] ?? (0, 0)
            entry.correct += item.correct ? 1 : 0
            entry.total += 1
            counts[item.category] = entry
        }

        var contributions: [(n: Double, p: Double, pSD: Double)] = []
        var byTopic: [ExamTopicResult] = []
        var testedTopics: [String] = []
        var untestedTopics: [String] = []
        var coveredWeight = 0.0
        var totalWeight = 0.0

        for slug in Blueprint.slugs {
            let blueprint = Blueprint.byCategory[slug]!
            totalWeight += blueprint
            let nQuestions = blueprint * Double(ReadinessTable.scoredQuestionCount)
            let entry = counts[slug] ?? (0, 0)
            let tested = entry.total >= minTopicQuestions

            let p: Double
            let pSD: Double
            if tested {
                coveredWeight += blueprint
                testedTopics.append(slug)
                let posterior = betaPosterior(correct: entry.correct, total: entry.total)
                p = posterior.mean
                pSD = posterior.sd
            } else {
                untestedTopics.append(slug)
                p = guessBaseline
                pSD = 0.0
            }

            contributions.append((nQuestions, p, pSD))
            byTopic.append(ExamTopicResult(
                category: slug,
                blueprint: blueprint,
                nExam: entry.total,
                correct: entry.correct,
                p: p,
                pSD: pSD,
                tested: tested
            ))
        }

        let coveragePct = totalWeight > 0 ? coveredWeight / totalWeight : 0.0

        var result = ExamResult(
            total: served,
            nAnswered: nAnswered,
            correct: correct,
            incorrect: incorrect,
            skipped: skipped,
            accuracy: accuracy,
            rawActual: rawActualScore(correct: correct, incorrect: incorrect),
            coveragePct: coveragePct,
            coverageGate: coverageGate,
            scaled: nil, low: nil, high: nil, raw: nil,
            expectedCorrect: nil,
            abstain: true,
            reason: nil,
            byTopic: byTopic,
            testedTopics: testedTopics,
            untestedTopics: untestedTopics
        )

        if nAnswered == 0 {
            result.reason = reasonNoAnswers
            return result
        }
        if coveragePct < coverageGate {
            result.reason = reasonAbstain
            return result
        }

        let projection = ReadinessTable.projectScaledScore(
            contributions: contributions,
            nTotal: Double(ReadinessTable.scoredQuestionCount)
        )
        result.scaled = projection.scaled
        result.low = projection.low
        result.high = projection.high
        result.raw = projection.raw
        result.expectedCorrect = projection.expectedCorrect
        result.abstain = false
        result.reason = nil
        return result
    }

    /// Jeffreys-Beta point and standard deviation for a topic's exam accuracy
    /// (a Beta(0.5, 0.5) prior updated by correct/total). One-for-one on a single
    /// question reads as 0.75 with a wide spread, not a false 1.0.
    static func betaPosterior(correct: Int, total: Int) -> (mean: Double, sd: Double) {
        let a = Double(correct) + 0.5
        let b = Double(total - correct) + 0.5
        let sum = a + b
        let mean = a / sum
        let variance = (a * b) / (sum * sum * (sum + 1.0))
        return (mean, variance.squareRoot())
    }

    /// The exam's own formula-scored raw over the questions it sat:
    /// round(correct - incorrect/4), clamped to the table's domain.
    static func rawActualScore(correct: Int, incorrect: Int) -> Int {
        let value = Double(correct) - Double(incorrect) / 4.0
        let clamped = min(max(value, Double(ReadinessTable.rawMin)), Double(ReadinessTable.rawMax))
        return Int(Foundation.floor(clamped + 0.5))
    }
}
