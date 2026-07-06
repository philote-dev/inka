// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Performance (the honest per-topic transfer signal) for the iOS companion. A
// faithful native port of pylib/anki/pgrep/performance.py: it answers "can you
// get a new, unseen exam-style problem right" per topic, P(correct), computed
// from the ATTEMPT LOG (not FSRS alone), because it is transfer, not recall.
//
// Model (Performance Factors Analysis, a calibrated logistic over four
// interpretable predictors), calibration (post-hoc beta), and the honesty rules
// are ported line-for-line:
//   - mastery comes from the SAME primitive Memory uses (the memory ->
//     performance bridge), so Memory and Performance never disagree; unknown
//     mastery falls back to a neutral 0.5;
//   - each per-topic score ships an 80% central interval whose width shrinks
//     with the number of distinct clean attempts (a Beta width model centered on
//     the calibrated prediction, NOT a rate posterior);
//   - a topic abstains until it has k_perf clean attempts AND its interval is
//     tighter than max_interval_width. With an empty attempt log every topic
//     abstains, which is the correct behavior (never a fabricated number).
//
// The learned coefficients / calibration params are defaults from the offline
// synthetic fit, identical to the desktop constants.

import Foundation

// MARK: - Result shape

/// Per-category Performance breakdown row (performance.by_topic entries).
struct PerformanceTopic: Sendable, Equatable {
    var category: String
    var blueprint: Double
    var value: ScoreValue
    var nAttempts: Int
}

/// The Performance result, matching the shape of performance.performance_score.
struct PerformanceResult: Sendable, Equatable {
    var overall: ScoreValue
    var byTopic: [PerformanceTopic]
    var kPerf: Int
    var lastUpdated: Date?
}

// MARK: - Learned model constants (defaults from the offline synthetic fit)

/// The four PFA logistic coefficients plus the intercept. `bDifficulty` is
/// stored positive and subtracted in the logit (harder -> less likely).
struct PFACoefficients: Sendable {
    let b0: Double
    let bMastery: Double
    let bDifficulty: Double
    let gSuccess: Double
    let gFailure: Double

    func logit(
        mastery: Double,
        difficultyNorm: Double,
        recentSuccesses: Double,
        recentFailures: Double
    ) -> Double {
        b0
            + bMastery * mastery
            - bDifficulty * difficultyNorm
            + gSuccess * recentSuccesses
            + gFailure * recentFailures
    }
}

/// Beta calibration (Kull et al. 2017): sigma(c + a*ln s - b*ln(1-s)).
struct BetaCalibration: Sendable {
    let a: Double
    let b: Double
    let c: Double

    func calibrate(_ raw: Double) -> Double {
        let s = PerformanceMath.clamp(raw, 1e-6, 1.0 - 1e-6)
        return PerformanceMath.sigmoid(c + a * Foundation.log(s) - b * Foundation.log(1.0 - s))
    }
}

enum PerformanceScore {
    // --- tunable thresholds (config, not magic; three-scores.md §8) ----------

    /// A topic needs at least this many clean attempts to show a number.
    static let kPerfDefault = 8
    /// A scored topic's 80% interval wider than this abstains (imprecise).
    static let maxIntervalWidthDefault = 0.40
    /// M3/M4 recency window: wins/misses over the last N in-topic attempts.
    static let recencyWindowDefault = 8
    /// Floor on the effective attempt count (interval concentration), not a rate
    /// prior; the interval is always centered on the calibrated prediction.
    static let poolingStrengthDefault = 4.0
    /// Latency data-quality filter (M5): attempts faster than this are guesses.
    static let minResponseMsDefault = 2000.0

    static let reasonThin = "Not enough attempts yet"
    static let reasonImprecise = "Estimate not precise enough yet"

    /// Max entropy when Memory abstains; middle of the 1..5 authored scale.
    static let masteryNeutral = 0.5
    static let difficultyNeutral = 3.0

    /// Defaults produced by the offline synthetic fit (placeholders until a
    /// real-cohort fit); identical to performance.DEFAULT_COEFFICIENTS.
    static let defaultCoefficients = PFACoefficients(
        b0: -0.3396,
        bMastery: 2.1080,
        bDifficulty: 1.7265,
        gSuccess: 0.1716,
        gFailure: -0.2200
    )
    static let defaultCalibration = BetaCalibration(a: 1.4173, b: 0.9346, c: 0.8804)

    /// Calibrated P(correct) for one topic's feature vector (the PFA point).
    /// `difficulty` is on the authored 1..5 scale (normalized internally).
    static func performanceProbability(
        mastery: Double,
        difficulty: Double,
        recentSuccesses: Double,
        recentFailures: Double,
        coefficients: PFACoefficients = defaultCoefficients,
        calibration: BetaCalibration = defaultCalibration
    ) -> Double {
        let raw = PerformanceMath.sigmoid(coefficients.logit(
            mastery: mastery,
            difficultyNorm: PerformanceMath.difficultyNorm(difficulty),
            recentSuccesses: recentSuccesses,
            recentFailures: recentFailures
        ))
        return calibration.calibrate(raw)
    }

    /// Fold clean attempts into a Performance result. `masteryByCategory` is the
    /// per-category Memory point (the bridge); a category absent from it falls
    /// back to the neutral mastery. `events` should be oldest-first (the recency
    /// window relies on it). A line-for-line port of performance_score's math.
    static func compute(
        events: [AttemptEvent],
        masteryByCategory: [String: Double],
        now: Date = Date(),
        kPerf: Int = kPerfDefault,
        recencyWindow: Int = recencyWindowDefault,
        maxIntervalWidth: Double = maxIntervalWidthDefault,
        poolingStrength: Double = poolingStrengthDefault,
        minResponseMs: Double = minResponseMsDefault,
        coefficients: PFACoefficients = defaultCoefficients,
        calibration: BetaCalibration = defaultCalibration
    ) -> PerformanceResult {
        // Group clean, on-blueprint attempts by category, preserving order.
        var cleanByCategory: [String: [AttemptEvent]] = [:]
        for event in events {
            guard Blueprint.byCategory[event.category] != nil else { continue }
            guard event.isClean(minResponseMs: minResponseMs) else { continue }
            cleanByCategory[event.category, default: []].append(event)
        }

        var byTopic: [PerformanceTopic] = []
        // (weight, point, variance) for each scored category.
        var scored: [(weight: Double, point: Double, variance: Double)] = []
        var totalAttempts = 0

        for slug in Blueprint.slugs {
            let blueprint = Blueprint.byCategory[slug]!
            let topicEvents = cleanByCategory[slug] ?? []
            let n = topicEvents.count
            totalAttempts += n

            if n < kPerf {
                byTopic.append(PerformanceTopic(
                    category: slug,
                    blueprint: blueprint,
                    value: .abstaining(reasonThin),
                    nAttempts: n
                ))
                continue
            }

            let mastery = masteryByCategory[slug] ?? masteryNeutral
            let features = topicFeatures(topicEvents, recencyWindow: recencyWindow)
            let point = performanceProbability(
                mastery: mastery,
                difficulty: features.difficulty,
                recentSuccesses: Double(features.successes),
                recentFailures: Double(features.failures),
                coefficients: coefficients,
                calibration: calibration
            )

            // Coverage (M6) as interval widener: attempts over few repeated items
            // carry less information, so deflate their evidence contribution.
            let coverageFactor = features.distinct > 0
                ? min(1.0, Double(features.distinct) / Double(kPerf))
                : 1.0
            let nEff = poolingStrength + Double(n) * coverageFactor
            let (low, high) = PerformanceMath.betaInterval(point: point, nEff: nEff)

            if (high - low) > maxIntervalWidth {
                byTopic.append(PerformanceTopic(
                    category: slug,
                    blueprint: blueprint,
                    value: .abstaining(reasonImprecise),
                    nAttempts: n
                ))
                continue
            }

            byTopic.append(PerformanceTopic(
                category: slug,
                blueprint: blueprint,
                value: ScoreValue(point: point, low: low, high: high, abstain: false, reason: nil),
                nAttempts: n
            ))
            scored.append((blueprint, point, PerformanceMath.betaVariance(point: point, nEff: nEff)))
        }

        return PerformanceResult(
            overall: overall(scored),
            byTopic: byTopic,
            kPerf: kPerf,
            lastUpdated: totalAttempts > 0 ? now : nil
        )
    }

    // MARK: - Feature extraction

    private static func topicFeatures(
        _ events: [AttemptEvent],
        recencyWindow: Int
    ) -> (difficulty: Double, successes: Int, failures: Int, distinct: Int) {
        let window = recencyWindow > 0 ? Array(events.suffix(recencyWindow)) : events
        let successes = window.reduce(0) { $0 + ($1.correct ? 1 : 0) }
        let failures = window.count - successes

        let diffs = events.compactMap(\.difficulty)
        let difficulty = diffs.isEmpty
            ? difficultyNeutral
            : diffs.reduce(0, +) / Double(diffs.count)

        let items = Set(events.compactMap(\.itemNoteId))
        return (difficulty, successes, failures, items.count)
    }

    private static func overall(
        _ scored: [(weight: Double, point: Double, variance: Double)]
    ) -> ScoreValue {
        guard !scored.isEmpty else { return .abstaining(reasonThin) }
        let totalWeight = scored.reduce(0) { $0 + $1.weight }
        let point = scored.reduce(0) { $0 + $1.weight * $1.point } / totalWeight
        let variance = scored.reduce(0.0) { acc, entry in
            let w = entry.weight / totalWeight
            return acc + w * w * entry.variance
        }
        let sd = variance.squareRoot()
        return ScoreValue(
            point: point,
            low: PerformanceMath.clamp01(point - PerformanceMath.z80 * sd),
            high: PerformanceMath.clamp01(point + PerformanceMath.z80 * sd),
            abstain: false,
            reason: nil
        )
    }
}

// MARK: - Pure math (no Collection needed; unit-testable in isolation)

/// The numeric primitives Performance needs: the logistic, the difficulty
/// normalization, and the Beta interval (regularized incomplete beta by Lentz's
/// method + bisection PPF). Ported from performance.py's private helpers.
enum PerformanceMath {
    /// z for the 80% two-sided central interval (10th/90th normal percentiles).
    static let z80 = 1.2816
    /// Central-interval mass for the per-topic Beta interval.
    static let intervalMass = 0.80

    static func clamp(_ value: Double, _ lo: Double, _ hi: Double) -> Double {
        value < lo ? lo : (value > hi ? hi : value)
    }

    static func clamp01(_ value: Double) -> Double { clamp(value, 0.0, 1.0) }

    /// Overflow-safe logistic.
    static func sigmoid(_ x: Double) -> Double {
        if x >= 0.0 { return 1.0 / (1.0 + Foundation.exp(-x)) }
        let z = Foundation.exp(x)
        return z / (1.0 + z)
    }

    /// Authored difficulty 1..5 -> [0,1] via (d-1)/4 (matches the offline fit).
    static func difficultyNorm(_ difficulty: Double) -> Double {
        clamp01((difficulty - 1.0) / 4.0)
    }

    /// Continued fraction for the incomplete beta (Lentz's method, NR §6.4).
    private static func betacf(
        _ x: Double, _ a: Double, _ b: Double, itmax: Int = 200, eps: Double = 3e-12
    ) -> Double {
        let qab = a + b
        let qap = a + 1.0
        let qam = a - 1.0
        var c = 1.0
        var d = 1.0 - qab * x / qap
        if Swift.abs(d) < 1e-30 { d = 1e-30 }
        d = 1.0 / d
        var h = d
        for m in 1...itmax {
            let md = Double(m)
            let m2 = Double(2 * m)
            var aa = md * (b - md) * x / ((qam + m2) * (a + m2))
            d = 1.0 + aa * d
            if Swift.abs(d) < 1e-30 { d = 1e-30 }
            c = 1.0 + aa / c
            if Swift.abs(c) < 1e-30 { c = 1e-30 }
            d = 1.0 / d
            h *= d * c
            aa = -(a + md) * (qab + md) * x / ((a + m2) * (qap + m2))
            d = 1.0 + aa * d
            if Swift.abs(d) < 1e-30 { d = 1e-30 }
            c = 1.0 + aa / c
            if Swift.abs(c) < 1e-30 { c = 1e-30 }
            d = 1.0 / d
            let delta = d * c
            h *= delta
            if Swift.abs(delta - 1.0) < eps { break }
        }
        return h
    }

    /// Regularized incomplete beta I_x(a, b) in [0, 1] (NR §6.4).
    private static func betainc(_ x: Double, _ a: Double, _ b: Double) -> Double {
        if x <= 0.0 { return 0.0 }
        if x >= 1.0 { return 1.0 }
        let lnBeta = lgamma(a) + lgamma(b) - lgamma(a + b)
        let front = Foundation.exp(a * Foundation.log(x) + b * Foundation.log(1.0 - x) - lnBeta)
        if x < (a + 1.0) / (a + b + 2.0) {
            return front * betacf(x, a, b) / a
        }
        return 1.0 - front * betacf(1.0 - x, b, a) / b
    }

    /// Inverse of `betainc` in x via bisection (monotone in x).
    private static func betaPPF(_ q: Double, _ a: Double, _ b: Double) -> Double {
        if q <= 0.0 { return 0.0 }
        if q >= 1.0 { return 1.0 }
        var lo = 0.0
        var hi = 1.0
        for _ in 0..<80 {
            let mid = 0.5 * (lo + hi)
            if betainc(mid, a, b) < q { lo = mid } else { hi = mid }
        }
        return 0.5 * (lo + hi)
    }

    /// Beta (alpha, beta) for an interval centered on `point` with total
    /// concentration `nEff`. The +0.5 keeps both shape params positive at the
    /// extremes. A width model, not a rate posterior: `point` is fixed.
    private static func concentration(point: Double, nEff: Double) -> (Double, Double) {
        let p = clamp(point, 1e-6, 1.0 - 1e-6)
        let kappa = Swift.max(nEff, 0.0)
        return (kappa * p + 0.5, kappa * (1.0 - p) + 0.5)
    }

    /// The `mass` central interval of the width Beta, guaranteed to bracket `point`.
    static func betaInterval(
        point: Double, nEff: Double, mass: Double = intervalMass
    ) -> (low: Double, high: Double) {
        let (a, b) = concentration(point: point, nEff: nEff)
        let tail = (1.0 - mass) / 2.0
        let low = betaPPF(tail, a, b)
        let high = betaPPF(1.0 - tail, a, b)
        // The reported point must always sit inside its own interval.
        return (Swift.min(low, point), Swift.max(high, point))
    }

    /// Variance of the topic's width Beta (for the overall aggregate).
    static func betaVariance(point: Double, nEff: Double) -> Double {
        let (a, b) = concentration(point: point, nEff: nEff)
        let total = a + b
        return (a * b) / (total * total * (total + 1.0))
    }
}
