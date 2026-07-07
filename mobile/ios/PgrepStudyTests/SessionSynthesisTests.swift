// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Pins the end-of-session synthesis derivation (SessionSynthesizer): the
// first-try score, the wall-clock duration, the first-seen topic bars, and the
// AI-off pattern template (weakest topics with a miss, worst first, capped at
// three, stable on ties). A faithful port of anki.pgrep.tutor.session_synthesis
// / _synthesize, so these mirror the desktop payload. Deterministic by
// construction: pure functions only, like StudySessionTests.

import XCTest

final class SessionSynthesisTests: XCTestCase {
    private func outcome(_ category: String, _ correct: Bool, at answeredAt: Int = 0) -> SessionOutcome {
        SessionOutcome(category: category, correct: correct, answeredAt: answeredAt)
    }

    // MARK: Score

    func testScoreCountsFirstTryCorrectAndTotal() {
        let synthesis = SessionSynthesizer.synthesize(outcomes: [
            outcome("mechanics", true),
            outcome("mechanics", false),
            outcome("quantum", true),
        ])
        XCTAssertEqual(synthesis.score, SessionSynthesis.Score(correct: 2, total: 3))
        XCTAssertEqual(synthesis.ai, "off")
    }

    func testEmptySessionHasNoTopicsOrPatterns() {
        let synthesis = SessionSynthesizer.synthesize(outcomes: [])
        XCTAssertEqual(synthesis.score, SessionSynthesis.Score(correct: 0, total: 0))
        XCTAssertTrue(synthesis.byTopic.isEmpty)
        XCTAssertTrue(synthesis.patterns.isEmpty)
        XCTAssertEqual(synthesis.durationMin, 0)
        XCTAssertEqual(synthesis.reframe, "No problems landed this session.")
    }

    // MARK: Reframe (verbatim from tutor._reframe)

    func testReframeNoProblems() {
        XCTAssertEqual(
            SessionSynthesizer.reframe(total: 0, correct: 0),
            "No problems landed this session."
        )
    }

    func testReframeCleanRun() {
        XCTAssertEqual(
            SessionSynthesizer.reframe(total: 3, correct: 3),
            "A clean run today. The value now is keeping the mix hard enough to miss."
        )
    }

    func testReframeMixedRun() {
        XCTAssertEqual(
            SessionSynthesizer.reframe(total: 4, correct: 1),
            "In-session accuracy understates your learning. The misses are where "
                + "today's work happened; here is what they share."
        )
    }

    // MARK: Duration

    func testDurationIsWallClockMinutes() {
        // 1000s to 1600s is 600s -> 10 minutes.
        let synthesis = SessionSynthesizer.synthesize(outcomes: [
            outcome("mechanics", true, at: 1_000),
            outcome("quantum", false, at: 1_600),
        ])
        XCTAssertEqual(synthesis.durationMin, 10)
    }

    func testDurationRoundsToNearestMinute() {
        // 100s to 800s is 700s -> 11.67 min -> 12.
        XCTAssertEqual(
            SessionSynthesizer.durationMinutes([
                outcome("mechanics", true, at: 100),
                outcome("quantum", true, at: 800),
            ]),
            12
        )
    }

    func testDurationZeroWithFewerThanTwoTimedCommits() {
        XCTAssertEqual(SessionSynthesizer.durationMinutes([outcome("mechanics", true, at: 500)]), 0)
        XCTAssertEqual(SessionSynthesizer.durationMinutes([]), 0)
        // Untimed commits (answeredAt 0) never enter the window.
        XCTAssertEqual(
            SessionSynthesizer.durationMinutes([
                outcome("mechanics", true, at: 0),
                outcome("quantum", true, at: 0),
            ]),
            0
        )
    }

    // MARK: Topic bars

    func testTopicRowsInFirstSeenOrderWithCounts() {
        let topics = SessionSynthesizer.synthesize(outcomes: [
            outcome("mechanics", true),
            outcome("mechanics", false),
            outcome("electromagnetism", false),
            outcome("electromagnetism", false),
            outcome("quantum", true),
        ]).byTopic
        XCTAssertEqual(topics, [
            SynthesisTopic(topic: "mechanics", correct: 1, total: 2),
            SynthesisTopic(topic: "electromagnetism", correct: 0, total: 2),
            SynthesisTopic(topic: "quantum", correct: 1, total: 1),
        ])
    }

    func testAllCorrectTopicIsBarButNotPattern() {
        let synthesis = SessionSynthesizer.synthesize(outcomes: [
            outcome("mechanics", true),
            outcome("mechanics", true),
            outcome("quantum", false),
        ])
        XCTAssertEqual(synthesis.byTopic.map(\.topic), ["mechanics", "quantum"])
        XCTAssertEqual(synthesis.patterns.map(\.title), ["Quantum needs another pass"])
    }

    // MARK: Patterns (AI-off template)

    func testPatternsNameWeakestTopicsWorstFirst() {
        let patterns = SessionSynthesizer.synthesize(outcomes: [
            outcome("mechanics", true),
            outcome("mechanics", false), // mechanics 1/2 = 0.5
            outcome("electromagnetism", false),
            outcome("electromagnetism", false), // e&m 0/2 = 0.0
            outcome("quantum", true), // quantum 1/1, no miss, excluded
        ]).patterns
        XCTAssertEqual(patterns.count, 2)
        XCTAssertEqual(patterns[0], SynthesisPattern(
            title: "Electromagnetism needs another pass", count: 2, kind: .miss, evidence: ""
        ))
        XCTAssertEqual(patterns[1], SynthesisPattern(
            title: "Mechanics needs another pass", count: 1, kind: .miss, evidence: ""
        ))
    }

    func testCleanRunHasNoPatterns() {
        XCTAssertTrue(SessionSynthesizer.synthesize(outcomes: [
            outcome("mechanics", true),
            outcome("quantum", true),
        ]).patterns.isEmpty)
    }

    func testPatternsCapAtThree() {
        let patterns = SessionSynthesizer.synthesize(outcomes: [
            outcome("mechanics", false),
            outcome("electromagnetism", false),
            outcome("quantum", false),
            outcome("thermodynamics", false),
            outcome("atomic", false),
        ]).patterns
        XCTAssertEqual(patterns.count, 3)
    }

    func testPatternTiesKeepFirstSeenOrderAndSentenceCaseCompoundSlugs() {
        // Both 0/1 (tie); first-seen order wins. Compound slugs sentence-case.
        let patterns = SessionSynthesizer.synthesize(outcomes: [
            outcome("special_relativity", false),
            outcome("optics_waves", false),
        ]).patterns
        XCTAssertEqual(patterns.map(\.title), [
            "Special relativity needs another pass",
            "Optics waves needs another pass",
        ])
    }

    func testPatternCountIsMissCount() {
        let patterns = SessionSynthesizer.synthesize(outcomes: [
            outcome("mechanics", false),
            outcome("mechanics", false),
            outcome("mechanics", true),
        ]).patterns
        XCTAssertEqual(patterns.count, 1)
        XCTAssertEqual(patterns[0].count, 2)
    }
}
