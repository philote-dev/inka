// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Native Memory score for the iOS companion. This is a faithful port of the
// desktop fold in pylib/anki/pgrep/memory.py: per card the engine's own FSRS
// retrievability R (read via CardStats over FFI, so it equals desktop by
// construction), grouped by topic category, blueprint-weighted, with an 80%
// range and an honest abstain when a category has too few reviewed cards.
//
// The blueprint table and topic-tag parsing are duplicated here on purpose, the
// same cross-language boundary duplication the L1 contract mandates for the
// Rust/Python copies (docs_pgrep/reference/tag-and-attempt-log-schema.md §1). Do not
// factor these into a shared, synced source.

import Foundation

/// PGRE blueprint weights by category slug (fractions summing to 1.0), in
/// blueprint order. Mirrors pylib/anki/pgrep/blueprint.py.
enum Blueprint {
    static let ordered: [(slug: String, weight: Double)] = [
        ("mechanics", 0.20),
        ("electromagnetism", 0.18),
        ("quantum", 0.13),
        ("thermodynamics", 0.10),
        ("atomic", 0.10),
        ("optics_waves", 0.08),
        ("special_relativity", 0.06),
        ("lab", 0.06),
        ("specialized", 0.09),
    ]
    static let byCategory: [String: Double] = Dictionary(uniqueKeysWithValues: ordered.map { ($0.slug, $0.weight) })
    static let slugs: [String] = ordered.map(\.slug)
}

/// Two-level topic-tag parsing. Mirrors pylib/anki/pgrep/tags.py.
enum Topic {
    static let prefix = "topic::"

    /// Category slug for an item's tags: the 2nd `::` segment of the first
    /// `topic::` tag, lowercased. `unknown` if untagged or malformed. The first
    /// topic tag wins (multi-topic items are out of scope, per the L1 contract).
    static func category(forTags tags: [String]) -> String {
        guard let first = tags.first(where: { $0.lowercased().hasPrefix(prefix) }) else {
            return "unknown"
        }
        // "topic::mechanics::lagrangian" -> ["topic", "mechanics", "lagrangian"].
        let parts = first.components(separatedBy: "::")
        if parts.count >= 2, parts[0].lowercased() == "topic" {
            let cat = parts[1].trimmingCharacters(in: .whitespaces).lowercased()
            if !cat.isEmpty { return cat }
        }
        return "unknown"
    }

    /// The finest topic tag: the first `topic::…` tag verbatim, or nil if the
    /// item carries none. Mirrors tags.finest_topic; used to stamp an attempt's
    /// `topic` payload/tag so an iOS-written attempt matches a desktop one.
    static func finest(forTags tags: [String]) -> String? {
        tags.first { $0.lowercased().hasPrefix(prefix) }
    }
}

/// z for the 80% two-sided central interval (10th/90th normal percentiles).
private let z80 = 1.2816

private func clamp01(_ v: Double) -> Double { v < 0 ? 0 : (v > 1 ? 1 : v) }

/// One score's honesty payload: a point plus an 80% range, or an abstain.
struct ScoreValue: Sendable, Equatable {
    var point: Double?
    var low: Double?
    var high: Double?
    var abstain: Bool
    var reason: String?

    static func abstaining(_ reason: String) -> ScoreValue {
        ScoreValue(point: nil, low: nil, high: nil, abstain: true, reason: reason)
    }
}

/// Per-category Memory breakdown row.
struct TopicScore: Sendable, Equatable {
    var category: String
    var blueprint: Double
    var value: ScoreValue
    var nCards: Int
}

/// The Memory result, matching the shape of memory.memory_score.
struct MemoryResult: Sendable, Equatable {
    var overall: ScoreValue
    var byTopic: [TopicScore]
    var kMem: Int
    var lastUpdated: Date?

    /// Per-category Memory point (the memory -> performance bridge). Only scored
    /// categories appear; abstaining ones are absent, so Performance falls back
    /// to its neutral mastery for them (mirrors performance.mastery_by_category
    /// with its `None` fallback).
    var masteryByCategory: [String: Double] {
        var out: [String: Double] = [:]
        for topic in byTopic where topic.value.point != nil {
            out[topic.category] = topic.value.point
        }
        return out
    }
}

enum MemoryScore {
    static let abstainReason = "Not enough cards yet"
    static let kMemDefault = 5

    /// Fold `(category, retrievability)` samples into a Memory result. `samples`
    /// should already exclude cards with no retrievability (new/unreviewed).
    /// Cards whose category is not in the blueprint are ignored here too. This
    /// is a line-for-line port of memory.memory_score's math.
    static func fold(samples: [(category: String, r: Double)], kMem: Int = kMemDefault, now: Date = Date()) -> MemoryResult {
        var counts: [String: Int] = [:]
        var sumR: [String: Double] = [:]
        var sumVar: [String: Double] = [:]

        for sample in samples {
            let category = sample.category
            guard Blueprint.byCategory[category] != nil else { continue }
            let r = clamp01(sample.r)
            counts[category, default: 0] += 1
            sumR[category, default: 0] += r
            sumVar[category, default: 0] += r * (1 - r)
        }

        var byTopic: [TopicScore] = []
        // (weight, point, variance-of-the-mean) for each scored category.
        var scored: [(weight: Double, point: Double, varMean: Double)] = []
        var totalReviewed = 0

        for slug in Blueprint.slugs {
            let weight = Blueprint.byCategory[slug]!
            let n = counts[slug, default: 0]
            totalReviewed += n
            if n < kMem {
                byTopic.append(TopicScore(
                    category: slug,
                    blueprint: weight,
                    value: .abstaining(abstainReason),
                    nCards: n
                ))
                continue
            }
            let point = sumR[slug]! / Double(n)
            let sd = (sumVar[slug]!).squareRoot() / Double(n)
            byTopic.append(TopicScore(
                category: slug,
                blueprint: weight,
                value: ScoreValue(
                    point: point,
                    low: clamp01(point - z80 * sd),
                    high: clamp01(point + z80 * sd),
                    abstain: false,
                    reason: nil
                ),
                nCards: n
            ))
            scored.append((weight, point, sumVar[slug]! / Double(n * n)))
        }

        return MemoryResult(
            overall: overall(scored),
            byTopic: byTopic,
            kMem: kMem,
            lastUpdated: totalReviewed > 0 ? now : nil
        )
    }

    private static func overall(_ scored: [(weight: Double, point: Double, varMean: Double)]) -> ScoreValue {
        guard !scored.isEmpty else { return .abstaining(abstainReason) }
        let totalWeight = scored.reduce(0) { $0 + $1.weight }
        let point = scored.reduce(0) { $0 + $1.weight * $1.point } / totalWeight
        let variance = scored.reduce(0) { acc, s in
            let w = s.weight / totalWeight
            return acc + w * w * s.varMean
        }
        let sd = variance.squareRoot()
        return ScoreValue(
            point: point,
            low: clamp01(point - z80 * sd),
            high: clamp01(point + z80 * sd),
            abstain: false,
            reason: nil
        )
    }
}
