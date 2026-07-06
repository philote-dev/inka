// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Coverage ledger for the iOS companion: how much of the blueprint you have
// started on. A faithful port of pylib/anki/pgrep/coverage.py: a category is
// covered once it has at least one reviewed card, and the overall figure is the
// summed blueprint weight of the covered categories. It is a thin, honest ledger
// built entirely on top of the native Memory fold (MemoryResult), so Coverage
// and Memory can never disagree and no retrievability is recomputed here.
//
// The 0.70 gate is the Readiness coverage gate; Coverage shows it but does not
// enforce it (Readiness does, in ReadinessScore).

import Foundation

/// Per-category coverage row. Mirrors coverage.coverage's `by_topic` entries.
struct CoverageTopic: Sendable, Equatable {
    var category: String
    var blueprint: Double
    var covered: Bool
    var nCards: Int
    /// The category's Memory point, or nil while the topic still abstains.
    var memoryPoint: Double?
}

/// The Coverage result, matching the shape of coverage.coverage.
struct CoverageResult: Sendable, Equatable {
    var overallPct: Double
    var gate: Double
    var byTopic: [CoverageTopic]
}

enum CoverageScore {
    /// The Readiness coverage gate (three-scores.md §3/§5): shown here, enforced
    /// in ReadinessScore. Kept in step with CoverageScore.gate below.
    static let gate = 0.70

    /// Fold a Memory result into the coverage ledger. `covered` is the L2
    /// definition (at least one reviewed card); `overallPct` is the summed
    /// blueprint weight of the covered categories over the whole blueprint.
    static func compute(memory: MemoryResult) -> CoverageResult {
        var byTopic: [CoverageTopic] = []
        var coveredWeight = 0.0
        var totalWeight = 0.0

        for entry in memory.byTopic {
            let covered = entry.nCards >= 1
            totalWeight += entry.blueprint
            if covered { coveredWeight += entry.blueprint }
            byTopic.append(CoverageTopic(
                category: entry.category,
                blueprint: entry.blueprint,
                covered: covered,
                nCards: entry.nCards,
                memoryPoint: entry.value.point
            ))
        }

        let overallPct = totalWeight > 0 ? coveredWeight / totalWeight : 0.0
        return CoverageResult(overallPct: overallPct, gate: gate, byTopic: byTopic)
    }
}
