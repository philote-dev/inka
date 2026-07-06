// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Readiness (the projected PGRE scaled score, with a range) for the iOS
// companion. A faithful native port of pylib/anki/pgrep/readiness.py: it
// projects the PGRE 200-990 scaled score with an 80% range, leaning on
// Performance (transfer under exam conditions), and abstains honestly when
// coverage is too thin. Pure math over the Performance result + the blueprint +
// the embedded raw->scaled constants (readiness_constants.py). No AI.
//
// Pipeline:
//   1. per topic p_t = P(correct) from Performance; n_t = blueprint% * 100 exam
//      questions;
//   2. expected raw is a Poisson-binomial across topics (mean Σ n_t*p_t,
//      variance Σ n_t*p_t*(1-p_t));
//   3. raw -> scaled via the official conversion table, with the raw axis
//      formula-scored (raw = 1.25*correct - 0.25*n);
//   4. the range adds the sampling spread and the model spread (each topic's 80%
//      Performance interval), endpoints mapped through the table;
//   5. below the 70% coverage gate Readiness abstains and names the uncovered
//      exam. You cannot fake readiness over a hole.

import Foundation

// MARK: - Result shape

/// Per-category Readiness contribution (readiness.by_topic entries).
struct ReadinessTopic: Sendable, Equatable {
    var category: String
    var blueprint: Double
    var nQuestions: Double
    var p: Double
    var pSD: Double
    var nAttempts: Int
    var covered: Bool
    /// "performance" when the topic carried a real point, else "guess".
    var source: String
}

/// The Readiness result, matching the shape of readiness.readiness_score. The
/// point/range are on the 200-990 scaled band (not 0..1), so the UI renders
/// them as whole scores, not percentages.
struct ReadinessResult: Sendable, Equatable {
    var scaled: Int?
    var low: Int?
    var high: Int?
    var raw: Int?
    var rawLow: Int?
    var rawHigh: Int?
    var expectedCorrect: Double?
    var coveragePct: Double
    var coverageGate: Double
    var kPerf: Int
    var uncoveredTopics: [String]
    var scoredAsGuess: [String]
    var abstain: Bool
    var reason: String?
    var lastUpdated: Date?
    var byTopic: [ReadinessTopic]
}

extension ReadinessResult {
    /// The score-card payload for Readiness: a scaled point + scaled range on the
    /// 200-990 band, or an honest abstain that names what is missing. Rendered
    /// with `ScoreScale.scaled` so the number is never multiplied by 100.
    var scoreValue: ScoreValue {
        guard !abstain, let scaled else {
            return .abstaining(reason ?? ReadinessScore.reasonAbstain)
        }
        return ScoreValue(
            point: Double(scaled),
            low: low.map(Double.init),
            high: high.map(Double.init),
            abstain: false,
            reason: nil
        )
    }

    /// Readiness reads out its coverage rather than an interval width, matching
    /// desktop Progress ("N percent covered").
    var howSureDetail: String? {
        guard !abstain else { return nil }
        return "\(Int((coveragePct * 100).rounded())) percent covered"
    }
}

enum ReadinessScore {
    /// Number of answer choices on a PGRE item; guessing is 1/this.
    static let choicesPerQuestion = 5
    static let guessBaseline = 1.0 / 5.0
    static let reasonAbstain = "Not enough of the exam is covered yet"

    /// Project Readiness from a Performance result. `assumeAllAttempted` uses the
    /// table's formula-scored raw (the default). A line-for-line port of
    /// readiness_score's coverage-gated projection.
    static func compute(
        performance: PerformanceResult,
        coverageGate: Double = CoverageScore.gate,
        examQuestionCount: Int = ReadinessTable.scoredQuestionCount,
        guessBaseline: Double = guessBaseline,
        assumeAllAttempted: Bool = true
    ) -> ReadinessResult {
        let kPerf = performance.kPerf

        var contributions: [(n: Double, p: Double, pSD: Double)] = []
        var byTopic: [ReadinessTopic] = []
        var uncoveredTopics: [String] = []
        var coveredWeight = 0.0
        var totalWeight = 0.0

        for entry in performance.byTopic {
            let blueprint = entry.blueprint
            let nAttempts = entry.nAttempts
            let nQuestions = blueprint * Double(examQuestionCount)
            totalWeight += blueprint

            let covered = nAttempts >= kPerf
            if covered {
                coveredWeight += blueprint
            } else {
                uncoveredTopics.append(entry.category)
            }

            let p: Double
            let pSD: Double
            let source: String
            if let point = entry.value.point {
                p = point
                pSD = topicSD(entry.value)
                source = "performance"
            } else {
                // Uncovered, or covered-but-imprecise: fall back to the guessing
                // baseline so the projection still spans this topic's questions
                // (contributes ~0 raw under formula scoring).
                p = guessBaseline
                pSD = 0.0
                source = "guess"
            }

            contributions.append((nQuestions, p, pSD))
            byTopic.append(ReadinessTopic(
                category: entry.category,
                blueprint: blueprint,
                nQuestions: nQuestions,
                p: p,
                pSD: pSD,
                nAttempts: nAttempts,
                covered: covered,
                source: source
            ))
        }

        let coveragePct = totalWeight > 0 ? coveredWeight / totalWeight : 0.0

        // Covered topics that Performance still could not score (imprecise) fell
        // back to the guess baseline; surfaced so they cannot bluff the gate.
        let scoredAsGuess = byTopic
            .filter { $0.source == "guess" && $0.covered }
            .map(\.category)

        var result = ReadinessResult(
            scaled: nil, low: nil, high: nil,
            raw: nil, rawLow: nil, rawHigh: nil,
            expectedCorrect: nil,
            coveragePct: coveragePct,
            coverageGate: coverageGate,
            kPerf: kPerf,
            uncoveredTopics: uncoveredTopics,
            scoredAsGuess: scoredAsGuess,
            abstain: true,
            reason: nil,
            lastUpdated: performance.lastUpdated,
            byTopic: byTopic
        )

        if coveragePct < coverageGate {
            result.abstain = true
            result.reason = reasonAbstain
            return result
        }

        let projection = ReadinessTable.projectScaledScore(
            contributions: contributions,
            nTotal: Double(examQuestionCount),
            assumeAllAttempted: assumeAllAttempted
        )
        result.scaled = projection.scaled
        result.low = projection.low
        result.high = projection.high
        result.raw = projection.raw
        result.rawLow = projection.rawLow
        result.rawHigh = projection.rawHigh
        result.expectedCorrect = projection.expectedCorrect
        result.abstain = false
        result.reason = nil
        return result
    }

    /// Model sd on p_t from a scored topic's 80% Performance interval:
    /// (high - low) is the 80% width, so sd ~= width / (2*z). 0 when the topic
    /// has no interval (it abstains and falls back to the guessing baseline).
    private static func topicSD(_ value: ScoreValue) -> Double {
        guard let low = value.low, let high = value.high else { return 0.0 }
        return (high - low) / (2.0 * ReadinessTable.z80)
    }
}

// MARK: - The embedded conversion table + raw math (pure, testable)

/// The PGRE raw-to-scaled conversion constants and the projection math. Ported
/// from readiness_constants.py + readiness.py's pure functions. The table is a
/// plain factual numeric mapping (constants only), highest raw first, contiguous
/// over [0, 100], scaled strictly increasing with raw.
enum ReadinessTable {
    static let z80 = 1.2816

    /// The PGRE has this many scored questions; the raw axis spans them.
    static let scoredQuestionCount = 100
    /// Inclusive raw domain of the table (a raw outside this is clamped).
    static let rawMin = 0
    static let rawMax = 100

    /// (rawMin, rawMax, scaled) per row.
    static let rawToScaled: [(rawMin: Int, rawMax: Int, scaled: Int)] = [
        (84, 100, 990), (83, 83, 980), (81, 82, 970), (80, 80, 960),
        (79, 79, 950), (77, 78, 940), (76, 76, 930), (75, 75, 920),
        (73, 74, 910), (72, 72, 900), (71, 71, 890), (69, 70, 880),
        (68, 68, 870), (67, 67, 860), (65, 66, 850), (64, 64, 840),
        (63, 63, 830), (61, 62, 820), (60, 60, 810), (59, 59, 800),
        (57, 58, 790), (56, 56, 780), (55, 55, 770), (53, 54, 760),
        (52, 52, 750), (51, 51, 740), (49, 50, 730), (48, 48, 720),
        (47, 47, 710), (45, 46, 700), (44, 44, 690), (43, 43, 680),
        (41, 42, 670), (40, 40, 660), (39, 39, 650), (37, 38, 640),
        (36, 36, 630), (35, 35, 620), (33, 34, 610), (32, 32, 600),
        (30, 31, 590), (29, 29, 580), (28, 28, 570), (26, 27, 560),
        (25, 25, 550), (24, 24, 540), (22, 23, 530), (21, 21, 520),
        (20, 20, 510), (18, 19, 500), (17, 17, 490), (16, 16, 480),
        (14, 15, 470), (13, 13, 460), (12, 12, 450), (10, 11, 440),
        (9, 9, 430), (8, 8, 420), (6, 7, 410), (5, 5, 400),
        (4, 4, 390), (2, 3, 380), (1, 1, 370), (0, 0, 360),
    ]

    private static func clamp(_ value: Double, _ lo: Double, _ hi: Double) -> Double {
        value < lo ? lo : (value > hi ? hi : value)
    }

    /// Round to the nearest integer, halves up (the table's round(...)).
    private static func roundHalfUp(_ value: Double) -> Int {
        Int(Foundation.floor(value + 0.5))
    }

    /// Map a formula-scored raw to its PGRE scaled score. `raw` is rounded and
    /// clamped to the table's domain before lookup.
    static func rawToScaledScore(_ raw: Double) -> Int {
        let r = roundHalfUp(clamp(raw, Double(rawMin), Double(rawMax)))
        for row in rawToScaled where row.rawMin <= r && r <= row.rawMax {
            return row.scaled
        }
        // Unreachable: the table covers the whole clamped domain. Clamp defensively.
        return rawToScaled.last!.scaled
    }

    /// Mean and variance of the total-correct Poisson-binomial. `contributions`
    /// is (n_t, p_t) per topic.
    static func poissonBinomialStats(
        _ contributions: [(n: Double, p: Double)]
    ) -> (mean: Double, variance: Double) {
        let mean = contributions.reduce(0.0) { $0 + $1.n * $1.p }
        let variance = contributions.reduce(0.0) { $0 + $1.n * $1.p * (1.0 - $1.p) }
        return (mean, variance)
    }

    /// Convert an expected-correct count to the table's formula-scored raw.
    /// With `assumeAllAttempted`: incorrect = n - correct, so
    /// raw = 1.25*correct - 0.25*n. Rights-only returns correct unchanged.
    static func correctToRaw(
        correct: Double, nTotal: Double, assumeAllAttempted: Bool = true
    ) -> Double {
        assumeAllAttempted ? 1.25 * correct - 0.25 * nTotal : correct
    }

    struct Projection: Sendable, Equatable {
        var expectedCorrect: Double
        var correctSD: Double
        var raw: Int
        var rawLow: Int
        var rawHigh: Int
        var scaled: Int
        var low: Int
        var high: Int
    }

    /// Project the scaled score + 80% interval from per-topic contributions
    /// (n_t, p_t, p_sd_t). The total-correct variance combines the
    /// Poisson-binomial sampling term with the model term Σ (n_t*p_sd_t)^2.
    static func projectScaledScore(
        contributions: [(n: Double, p: Double, pSD: Double)],
        nTotal: Double,
        assumeAllAttempted: Bool = true,
        z: Double = z80
    ) -> Projection {
        let samplingPairs = contributions.map { (n: $0.n, p: $0.p) }
        let (meanCorrect, varSampling) = poissonBinomialStats(samplingPairs)
        let varModel = contributions.reduce(0.0) { $0 + ($1.n * $1.pSD) * ($1.n * $1.pSD) }
        let sdCorrect = (varSampling + varModel).squareRoot()

        let loCorrect = meanCorrect - z * sdCorrect
        let hiCorrect = meanCorrect + z * sdCorrect

        let rawPoint = correctToRaw(correct: meanCorrect, nTotal: nTotal, assumeAllAttempted: assumeAllAttempted)
        let rawLow = correctToRaw(correct: loCorrect, nTotal: nTotal, assumeAllAttempted: assumeAllAttempted)
        let rawHigh = correctToRaw(correct: hiCorrect, nTotal: nTotal, assumeAllAttempted: assumeAllAttempted)

        return Projection(
            expectedCorrect: meanCorrect,
            correctSD: sdCorrect,
            raw: roundHalfUp(clamp(rawPoint, Double(rawMin), Double(rawMax))),
            rawLow: roundHalfUp(clamp(rawLow, Double(rawMin), Double(rawMax))),
            rawHigh: roundHalfUp(clamp(rawHigh, Double(rawMin), Double(rawMax))),
            scaled: rawToScaledScore(rawPoint),
            low: rawToScaledScore(rawLow),
            high: rawToScaledScore(rawHigh)
        )
    }
}
