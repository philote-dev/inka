// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// The end-of-session consolidation (session synthesis), the pure model plus the
// derivation. Ported from anki.pgrep.tutor.session_synthesis / _synthesize
// (pylib/anki/pgrep/tutor.py) and matched to the shared payload contract in
// ts/lib/pgrep/synthesis.ts, which the desktop SessionSynthesis.svelte renders.
//
// The desktop takes a session id and reads the tagged attempt log for it, then
// keeps only the clean, first-try attempts (ladder_depth 0) to drive the score,
// the topic bars, and the miss grouping. The iOS interleaved session already
// records exactly those clean commits as it runs (a tutor retry never writes an
// attempt), so this port derives the same payload from the session's own
// outcomes instead of re-reading the log. That needs no engine read and does not
// wait on the asynchronous attempt write, yet it counts the identical events.
//
// AI is off on the phone (offline-first), so only the AI-off branch of the
// desktop synthesis applies: the pattern cards name the weakest topics that
// still carry a miss, with no model-written evidence. The AI-on miss grouping is
// out of scope here by construction, not dropped silently.
//
// This file is the pure, testable core (no SwiftUI, no engine), exercised by
// SessionSynthesisTests; SessionSynthesisView.swift renders it.

import Foundation

/// One clean, committed, first-try problem outcome from the finished session:
/// the blueprint category, whether the commit was correct, and when it landed.
/// The iOS session appends one of these per commit, which is exactly the clean
/// (ladder_depth 0) attempt the desktop synthesis counts.
struct SessionOutcome: Sendable, Equatable {
    var category: String
    var correct: Bool
    /// Epoch seconds at commit, for the wall-clock duration (SynthesisTopic aside,
    /// only the min/max matter, so any consistent clock works).
    var answeredAt: Int
}

/// One topic row: a proportion-correct bar plus the honest small-n fraction.
/// Matches SynthesisTopic in synthesis.ts.
struct SynthesisTopic: Sendable, Equatable {
    /// Category slug (e.g. "electromagnetism"); the view maps it to a label.
    var topic: String
    var correct: Int
    var total: Int
}

/// A named pattern across the session: a recurring miss (AI off only ever emits
/// misses) or, with AI on, a strategy that saved answers. Matches
/// SynthesisPattern in synthesis.ts.
struct SynthesisPattern: Sendable, Equatable {
    enum Kind: String, Sendable, Equatable {
        case miss
        case save
    }

    var title: String
    var count: Int
    var kind: Kind
    /// One sentence that may carry inline LaTeX. Always empty on the AI-off path.
    var evidence: String
}

/// The end-of-session consolidation payload, matching SessionSynthesis in
/// synthesis.ts. `ai` records how it was produced; on the phone it is always
/// "off".
struct SessionSynthesis: Sendable, Equatable {
    /// First-try score for the session (retries excluded).
    struct Score: Sendable, Equatable {
        var correct: Int
        var total: Int
    }

    var ai: String
    var score: Score
    /// Wall-clock session length in whole minutes.
    var durationMin: Int
    /// One honest reframe sentence stated under the score.
    var reframe: String
    var byTopic: [SynthesisTopic]
    var patterns: [SynthesisPattern]
}

/// Derives the consolidation payload from the finished session's clean commits.
/// A faithful port of tutor.session_synthesis + tutor._synthesize (AI-off path).
enum SessionSynthesizer {
    /// Assemble the consolidation for a set of clean, first-try commits. Score,
    /// duration, and topic bars are computed; the pattern cards name the weakest
    /// topics that still carry a miss (the AI-off template).
    static func synthesize(outcomes: [SessionOutcome]) -> SessionSynthesis {
        let total = outcomes.count
        let correct = outcomes.reduce(0) { $0 + ($1.correct ? 1 : 0) }
        let byTopic = topicRows(outcomes)
        return SessionSynthesis(
            ai: "off",
            score: SessionSynthesis.Score(correct: correct, total: total),
            durationMin: durationMinutes(outcomes),
            reframe: reframe(total: total, correct: correct),
            byTopic: byTopic,
            patterns: patterns(byTopic: byTopic)
        )
    }

    /// One honest reframe line under the score. Warmth from a truer reading of the
    /// same number, never praise (desirable-difficulty study is meant to feel
    /// worse than it went). Verbatim from tutor._reframe so both hosts read alike.
    static func reframe(total: Int, correct: Int) -> String {
        if total == 0 {
            return "No problems landed this session."
        }
        if correct >= total {
            return "A clean run today. The value now is keeping the mix hard enough to miss."
        }
        return "In-session accuracy understates your learning. The misses are where "
            + "today's work happened; here is what they share."
    }

    /// Wall clock across the whole session in whole minutes, or 0 with fewer than
    /// two timed commits. Mirrors the round((max - min) / 60) in session_synthesis.
    static func durationMinutes(_ outcomes: [SessionOutcome]) -> Int {
        let times = outcomes.map(\.answeredAt).filter { $0 > 0 }
        guard times.count >= 2, let low = times.min(), let high = times.max() else {
            return 0
        }
        return Int((Double(high - low) / 60.0).rounded())
    }

    /// Per-topic bars in first-seen order (the desktop builds these by iterating
    /// the clean attempts into a dict, whose insertion order this matches).
    static func topicRows(_ outcomes: [SessionOutcome]) -> [SynthesisTopic] {
        var order: [String] = []
        var correct: [String: Int] = [:]
        var total: [String: Int] = [:]
        for outcome in outcomes {
            if total[outcome.category] == nil {
                order.append(outcome.category)
            }
            total[outcome.category, default: 0] += 1
            if outcome.correct {
                correct[outcome.category, default: 0] += 1
            }
        }
        return order.map {
            SynthesisTopic(topic: $0, correct: correct[$0] ?? 0, total: total[$0] ?? 0)
        }
    }

    /// The AI-off pattern cards: the weakest topics that still carry a miss,
    /// ordered by accuracy ascending, capped at three. The sort is stable on ties
    /// (first-seen order wins), matching Python's stable sort over the topic dict.
    /// Each card names a transferable topic to revisit, never a single question.
    static func patterns(byTopic: [SynthesisTopic]) -> [SynthesisPattern] {
        let weakest = byTopic.enumerated()
            .filter { $0.element.total - $0.element.correct > 0 }
            .sorted { lhs, rhs in
                let lAcc = Double(lhs.element.correct) / Double(max(1, lhs.element.total))
                let rAcc = Double(rhs.element.correct) / Double(max(1, rhs.element.total))
                if lAcc != rAcc { return lAcc < rAcc }
                return lhs.offset < rhs.offset
            }
            .prefix(3)
        return weakest.map { pair in
            let topic = pair.element
            return SynthesisPattern(
                title: "\(sentenceCase(topic.topic.replacingOccurrences(of: "_", with: " "))) needs another pass",
                count: topic.total - topic.correct,
                kind: .miss,
                evidence: ""
            )
        }
    }

    /// First character upper, the rest lower, matching Python str.capitalize() as
    /// used to title the AI-off pattern (e.g. "special_relativity" ->
    /// "Special relativity").
    static func sentenceCase(_ text: String) -> String {
        guard let first = text.first else { return text }
        return first.uppercased() + text.dropFirst().lowercased()
    }
}
