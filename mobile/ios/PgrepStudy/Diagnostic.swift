// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Diagnostic v0 (topic placement), a faithful port of the desktop read model in
// pylib/anki/pgrep/diagnostic.py. It places every blueprint category into one of
// two buckets, strong or rusty. The persona is post-undergraduate, so there is
// no cold bucket: a category the learner has never touched is rusty (needs work)
// until proven otherwise.
//
// Two signals feed each placement and combine deterministically (_placement_for
// in diagnostic.py):
//   1. A fresh quick-check outcome is decisive: correct -> strong, wrong ->
//      rusty. It overrides the Memory prior either way.
//   2. Otherwise the FSRS-R Memory prior: point >= STRONG_MEMORY_POINT (0.7) ->
//      strong.
//   3. With neither, default to rusty.
//
// The resulting snapshot ({category: "strong"|"rusty"} for every blueprint
// category) is persisted as small rolled-up state in the collection config under
// the SAME key and shape the desktop uses (DIAGNOSTIC_CONFIG_KEY), so the two
// hosts stay consistent and it syncs. Engine.swift reads/writes it; this file is
// the pure, testable core (placement rule + the two folds), split off like
// StudySession / ChoiceList so the host-less test bundle can pin it.
//
// The quick checks are duplicated here on purpose. Desktop keeps them as a
// backend constant (diagnostic.QUICK_CHECKS), not as cards / notes / tags, so the
// content has no engine-readable source; porting the constant is the same
// deliberate cross-language boundary duplication the L1 contract mandates for
// Blueprint / Topic (docs_pgrep/contracts/L1-coordination-schema.md §1). The
// prompt and choices carry delimited LaTeX (\( ... \)) so MathText typesets them
// like every other pgrep question.

import Foundation

/// The two placement buckets. No cold bucket (post-undergraduate persona).
/// Raw values match the desktop snapshot strings so the stored config is
/// byte-identical across hosts.
enum DiagnosticPlacement: String, Sendable, Equatable {
    case strong
    case rusty
}

/// An objective quick-check outcome (never a confidence / self-rating). Mirrors
/// diagnostic.OUTCOME_CORRECT / OUTCOME_WRONG.
enum DiagnosticOutcome: String, Sendable, Equatable {
    case correct
    case wrong
}

/// One category's objective quick check: a prompt, ordered choices (HTML with
/// LaTeX), and the 0-based index of the correct choice. Mirrors the value shape
/// of diagnostic.QUICK_CHECKS.
struct DiagnosticCheck: Sendable, Equatable {
    let prompt: String
    let choices: [String]
    let answer: Int
}

/// A blueprint category to place, with any existing placement. Mirrors one entry
/// of the diagnostic.topics response.
struct DiagnosticTopic: Sendable, Equatable, Identifiable {
    let category: String
    let blueprint: Double
    /// The placement stored by a previous run, or nil if never placed.
    let placement: DiagnosticPlacement?
    /// The reviewed-card count for this category (from Memory).
    let nCards: Int
    /// The category's quick check, or nil if it has none.
    let check: DiagnosticCheck?

    var id: String { category }
}

/// A quick check flattened with its category, ready for the surface to render.
struct DiagnosticCheckItem: Sendable, Equatable, Identifiable {
    let category: String
    let prompt: String
    let choices: [String]
    let answer: Int

    var id: String { category }
}

/// One category's fresh placement from a diagnostic pass. Mirrors one entry of
/// the diagnostic.place response.
struct PlacedTopic: Sendable, Equatable, Identifiable {
    let category: String
    let placement: DiagnosticPlacement

    var id: String { category }
}

/// Pure, testable core for the Diagnostic (no SwiftUI, no engine). Namespaced so
/// the host-less test bundle can pin the placement rule and the two folds.
enum Diagnostic {
    /// Collection-config key holding the rolled-up placement snapshot. Must equal
    /// diagnostic.DIAGNOSTIC_CONFIG_KEY so the desktop's pgrep_diagnostic_status
    /// sees a phone-written completion (and vice versa).
    static let configKey = "pgrep_diagnostic"

    /// A Memory point at or above this leans a category strong on the FSRS-R
    /// prior alone. Mirrors diagnostic.STRONG_MEMORY_POINT.
    static let strongMemoryPoint = 0.7

    /// One objective quick check per category, ported verbatim from
    /// diagnostic.QUICK_CHECKS. `answer` is the 0-based index of the correct
    /// choice. LaTeX delimiters are escaped for Swift string literals.
    static let quickChecks: [String: DiagnosticCheck] = [
        "mechanics": DiagnosticCheck(
            prompt: "A ball is dropped from rest. Ignoring air resistance, its speed after a time \\(t\\) is",
            choices: ["\\(gt\\)", "\\(\\tfrac{1}{2}gt^2\\)", "\\(2gt\\)", "\\(gt^2\\)"],
            answer: 0
        ),
        "electromagnetism": DiagnosticCheck(
            prompt: "The electric field of a point charge varies with distance \\(r\\) as",
            choices: ["\\(1/r\\)", "\\(1/r^2\\)", "\\(1/r^3\\)", "it stays constant"],
            answer: 1
        ),
        "quantum": DiagnosticCheck(
            prompt: "The commutator of position and momentum, \\([x, p]\\), equals",
            choices: ["\\(0\\)", "\\(i\\hbar\\)", "\\(\\hbar\\)", "\\(1\\)"],
            answer: 1
        ),
        "thermodynamics": DiagnosticCheck(
            prompt: "For an ideal gas, the pressure times the volume \\(PV\\) equals",
            choices: ["\\(nRT\\)", "\\(nR/T\\)", "\\(RT/n\\)", "\\(nRT^2\\)"],
            answer: 0
        ),
        "atomic": DiagnosticCheck(
            prompt: "The energy of a photon of frequency \\(f\\) is",
            choices: ["\\(hf\\)", "\\(h/f\\)", "\\(f/h\\)", "\\(hf^2\\)"],
            answer: 0
        ),
        "optics_waves": DiagnosticCheck(
            prompt: "For any wave, the speed equals the frequency times the",
            choices: ["wavelength", "period", "amplitude", "phase"],
            answer: 0
        ),
        "special_relativity": DiagnosticCheck(
            prompt: "As the speed approaches the speed of light, the Lorentz factor \\(\\gamma\\)",
            choices: ["approaches \\(1\\)", "approaches \\(0\\)", "grows without bound", "stays constant"],
            answer: 2
        ),
        "lab": DiagnosticCheck(
            prompt: "Averaging \\(N\\) independent measurements shrinks the standard error by a factor of",
            choices: ["\\(N\\)", "\\(\\sqrt{N}\\)", "\\(N^2\\)", "\\(1\\)"],
            answer: 1
        ),
        "specialized": DiagnosticCheck(
            prompt: "After one half-life, a radioactive sample falls to",
            choices: ["one half", "one quarter", "zero", "\\(1/e\\)"],
            answer: 0
        ),
    ]

    /// Combine the FSRS-R prior and the quick-check outcome into one bucket. A
    /// verbatim port of diagnostic._placement_for: the quick-check outcome is the
    /// fresh, decisive signal when present; the Memory prior is the fallback; the
    /// default is rusty.
    static func placement(memoryPoint: Double?, outcome: DiagnosticOutcome?) -> DiagnosticPlacement {
        switch outcome {
        case .correct:
            return .strong
        case .wrong:
            return .rusty
        case nil:
            if let memoryPoint, memoryPoint >= strongMemoryPoint {
                return .strong
            }
            return .rusty
        }
    }

    /// Grade a quick-check pick (0-based index) against its key. A nil pick
    /// (never answered) yields nil, so placement falls back to the Memory prior,
    /// exactly like an absent result on the desktop.
    static func outcome(selected: Int?, answer: Int) -> DiagnosticOutcome? {
        guard let selected else { return nil }
        return selected == answer ? .correct : .wrong
    }

    /// Build the topics to place, in blueprint order, with any stored placement,
    /// the reviewed-card count, and the quick check. A port of diagnostic.topics.
    /// An unrecognized stored value reads as no placement (mirrors the
    /// `placement in _PLACEMENTS else None` guard).
    static func topics(stored: [String: String], nCards: [String: Int]) -> [DiagnosticTopic] {
        Blueprint.ordered.map { slug, weight in
            DiagnosticTopic(
                category: slug,
                blueprint: weight,
                placement: stored[slug].flatMap(DiagnosticPlacement.init(rawValue:)),
                nCards: nCards[slug] ?? 0,
                check: quickChecks[slug]
            )
        }
    }

    /// The quick checks flattened with their category, in blueprint order, for
    /// the surface to step through.
    static func checkItems(_ topics: [DiagnosticTopic]) -> [DiagnosticCheckItem] {
        topics.compactMap { topic in
            topic.check.map {
                DiagnosticCheckItem(
                    category: topic.category,
                    prompt: $0.prompt,
                    choices: $0.choices,
                    answer: $0.answer
                )
            }
        }
    }

    /// Record a placement pass: grade each category's quick-check answer, combine
    /// it with the Memory prior, and place every blueprint category in blueprint
    /// order. A port of diagnostic.place's fold. `answers` maps a category to the
    /// learner's 0-based pick; a category with no answer falls back to the prior.
    /// `memoryPoints` maps a category to its Memory point (absent = abstaining,
    /// so no strong lean), matching memory.mastery_by_category.
    static func place(answers: [String: Int], memoryPoints: [String: Double]) -> [PlacedTopic] {
        Blueprint.ordered.map { slug, _ in
            let graded = quickChecks[slug].flatMap { outcome(selected: answers[slug], answer: $0.answer) }
            return PlacedTopic(
                category: slug,
                placement: placement(memoryPoint: memoryPoints[slug], outcome: graded)
            )
        }
    }

    /// The persisted snapshot dict ({category: "strong"|"rusty"}) for a set of
    /// placements. Matches the desktop config value written by diagnostic.place,
    /// so pgrep_diagnostic_status reads a phone completion identically.
    static func snapshot(from placed: [PlacedTopic]) -> [String: String] {
        Dictionary(uniqueKeysWithValues: placed.map { ($0.category, $0.placement.rawValue) })
    }
}
