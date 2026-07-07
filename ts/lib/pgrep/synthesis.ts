// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

// The session-synthesis (end-of-session consolidation) data contract, shared by
// the SessionSynthesis screen, the real Problems session end, and the dev-lab
// preview. Matches the pgrepTutorSynthesis backend payload
// (anki.pgrep.tutor.session_synthesis). See design/claude-design/session-synthesis.

/** One topic row: a proportion-correct bar plus an honest small-n fraction. */
export interface SynthesisTopic {
    /** Category slug (e.g. "electromagnetism"); the UI maps it to a label. */
    topic: string;
    correct: number;
    total: number;
}

/** A named pattern across the session: a recurring miss, or a strategy that saved
 *  answers. `evidence` is one sentence and may carry inline LaTeX. */
export interface SynthesisPattern {
    title: string;
    count: number;
    kind: "miss" | "save";
    evidence: string;
}

export interface SessionSynthesis {
    /** "on" | "off" | "error" — how the payload was produced. */
    ai: string;
    /** First-try score for the session (retries excluded). */
    score: { correct: number; total: number };
    /** Wall-clock session length in whole minutes. */
    duration_min: number;
    /** One honest reframe sentence stated under the score. */
    reframe: string;
    by_topic: SynthesisTopic[];
    patterns: SynthesisPattern[];
}
