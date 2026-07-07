// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Pins the Home manifold's Surface fold (ManifoldSurface.build), a port of
// pylib/anki/pgrep/manifold.py's manifold_surface: the nine exam areas always
// sit on the map, but the terrain folds three honest sources exactly as desktop
// does. Memory raises and lights an area (amber), measured Performance carries a
// lit area to blue then lilac, a diagnostic-strong area with no reviews shows a
// half-lit amber rise, and a rusty diagnostic (or a Memory below the floor)
// opens a hole. With everything abstaining / empty the map degrades to the
// honest unlit syllabus. The WKWebView host that draws the Surface
// (ManifoldWebView) stays in the app target; this pins the pure fold.
//
// Deterministic by construction: the fold is pure over its inputs, so these
// build synthetic Memory / Performance / placement and assert the resulting
// bumps, glows, holes, and dips per area.

import XCTest

final class ManifoldSurfaceTests: XCTestCase {
    // The reserved score hues, duplicated from manifold.ts SCORE_COLORS so a
    // silent hue drift is caught here too.
    private let amber = "235,203,139"
    private let blue = "129,161,193"
    private let lilac = "196,167,214"

    // MARK: Fresh collection (honest unlit syllabus)

    func testFreshCollectionIsTheUnlitSyllabus() {
        let surface = ManifoldSurface.build(memory: memoryResult(points: [:]))
        // Nine areas always sit on the map (the syllabus exists), even bases.
        XCTAssertEqual(surface.bumps.count, 9)
        XCTAssertEqual(surface.labels.count, 9)
        XCTAssertEqual(Set(surface.labels.map(\.topic)), Set(Blueprint.slugs))
        for bump in surface.bumps {
            XCTAssertEqual(bump.h, 0.16, accuracy: 1e-9)
        }
        // Nothing about the learner is fabricated: no peaks lit, no gaps opened.
        XCTAssertTrue(surface.glows.isEmpty)
        XCTAssertTrue(surface.holes.isEmpty)
        XCTAssertTrue(surface.dips.isEmpty)
    }

    func testBaselineIsTheUnlitSyllabus() {
        let surface = ManifoldSurface.baseline
        XCTAssertEqual(surface.bumps.count, 9)
        XCTAssertTrue(surface.glows.isEmpty)
        XCTAssertTrue(surface.holes.isEmpty)
        XCTAssertTrue(surface.dips.isEmpty)
    }

    // MARK: Memory-only terrain (the graceful-degradation baseline)

    func testMemoryOnlyLightsAmberAndOpensWeakHoles() throws {
        // A strong memory area lights amber and rises; a weak one (below the
        // floor) lights amber, opens a hole, and gets a dip. With no Performance
        // data, every glow stays amber, no blue or lilac.
        let surface = ManifoldSurface.build(
            memory: memoryResult(points: ["mechanics": 0.8, "quantum": 0.3])
        )

        let mechanics = entries(surface, "mechanics")
        XCTAssertEqual(try XCTUnwrap(mechanics.bump).h, 0.56, accuracy: 1e-9) // 0.16 + 0.5 * 0.8
        XCTAssertEqual(mechanics.glow?.c, amber)
        XCTAssertNil(mechanics.hole)
        XCTAssertNil(mechanics.dip)

        let quantum = entries(surface, "quantum")
        XCTAssertEqual(try XCTUnwrap(quantum.bump).h, 0.31, accuracy: 1e-9) // 0.16 + 0.5 * 0.3
        XCTAssertEqual(quantum.glow?.c, amber)
        XCTAssertNotNil(quantum.hole)
        XCTAssertNotNil(quantum.dip)

        XCTAssertTrue(surface.glows.allSatisfy { $0.c == amber })
    }

    func testEmptyPerformanceAndPlacementMatchMemoryOnly() {
        // The core degradation guarantee: an all-abstaining Performance and an
        // empty placement fold to exactly the Memory-only surface.
        let memory = memoryResult(points: ["mechanics": 0.8, "quantum": 0.3])
        let memoryOnly = ManifoldSurface.build(memory: memory)
        let withEmpties = ManifoldSurface.build(
            memory: memory,
            performance: performanceResult(points: [:]),
            placement: [:]
        )
        XCTAssertEqual(memoryOnly, withEmpties)
    }

    // MARK: Diagnostic placement fold

    func testRustyPlacementOpensHoleWithoutLighting() throws {
        // A rusty diagnostic with no reviews / attempts is an honest known gap:
        // it opens a hole and dip, but does not light and stays at the base.
        let surface = ManifoldSurface.build(
            memory: memoryResult(points: [:]),
            placement: ["thermodynamics": .rusty]
        )

        let thermo = entries(surface, "thermodynamics")
        XCTAssertNotNil(thermo.hole)
        XCTAssertNotNil(thermo.dip)
        XCTAssertNil(thermo.glow)
        XCTAssertEqual(try XCTUnwrap(thermo.bump).h, 0.16, accuracy: 1e-9)
        // Only the rusty area opens a gap.
        XCTAssertEqual(surface.holes.count, 1)
        XCTAssertEqual(surface.dips.count, 1)
    }

    func testStrongPlacementAffirmsHalfLitRise() throws {
        // A strong diagnostic with no reviews shows a half-lit amber rise (the
        // memorized-only stage) and no gap.
        let surface = ManifoldSurface.build(
            memory: memoryResult(points: [:]),
            placement: ["atomic": .strong]
        )

        let atomic = entries(surface, "atomic")
        XCTAssertEqual(try XCTUnwrap(atomic.bump).h, 0.41, accuracy: 1e-9) // 0.16 + 0.5 * 0.5
        XCTAssertEqual(atomic.glow?.c, amber)
        XCTAssertNil(atomic.hole)
        XCTAssertTrue(surface.holes.isEmpty)
    }

    // MARK: Performance progression coloring

    func testPerformanceCarriesHueBlueThenLilac() throws {
        // Memory abstains, but measured Performance lights the area: blue below
        // the ready bar, lilac at or above it, height read from Performance.
        let surface = ManifoldSurface.build(
            memory: memoryResult(points: [:]),
            performance: performanceResult(points: ["mechanics": 0.6, "electromagnetism": 0.72])
        )

        let mechanics = entries(surface, "mechanics")
        XCTAssertEqual(try XCTUnwrap(mechanics.bump).h, 0.46, accuracy: 1e-9) // 0.16 + 0.5 * 0.6
        XCTAssertEqual(mechanics.glow?.c, blue)
        XCTAssertNil(mechanics.hole)

        let em = entries(surface, "electromagnetism")
        XCTAssertEqual(try XCTUnwrap(em.bump).h, 0.52, accuracy: 1e-9) // 0.16 + 0.5 * 0.72
        XCTAssertEqual(em.glow?.c, lilac) // 0.72 >= ready bar 0.7
    }

    // MARK: Precedence (Memory > Performance > strong; rusty always gaps)

    func testMemoryPrecedesPerformanceAndRustyAlwaysGaps() throws {
        // Memory drives the height over Performance and strong placement, while
        // Performance still colors the glow by the furthest stage reached. A
        // rusty diagnostic opens a hole even atop a strong Memory (the learner's
        // flagged gap), and a strong one atop high Memory opens none.
        let surface = ManifoldSurface.build(
            memory: memoryResult(points: ["mechanics": 0.9, "quantum": 0.85]),
            performance: performanceResult(points: ["mechanics": 0.75]),
            placement: ["quantum": .rusty, "mechanics": .strong]
        )

        let mechanics = entries(surface, "mechanics")
        XCTAssertEqual(try XCTUnwrap(mechanics.bump).h, 0.61, accuracy: 1e-9) // memory 0.9, not perf
        XCTAssertEqual(mechanics.glow?.c, lilac) // perf 0.75 >= 0.7
        XCTAssertNil(mechanics.hole)

        let quantum = entries(surface, "quantum")
        XCTAssertEqual(try XCTUnwrap(quantum.bump).h, 0.585, accuracy: 1e-9) // 0.16 + 0.5 * 0.85
        XCTAssertEqual(quantum.glow?.c, amber) // no perf measured
        XCTAssertNotNil(quantum.hole) // rusty opens a gap despite strong memory
        XCTAssertNotNil(quantum.dip)
    }

    // MARK: Renderer contract (JSON the WKWebView consumes)

    func testSurfaceJSONRoundTripsWithAllRendererFields() {
        let surface = ManifoldSurface.build(
            memory: memoryResult(points: ["mechanics": 0.3]),
            performance: performanceResult(points: ["electromagnetism": 0.8]),
            placement: ["quantum": .rusty]
        )
        let json = surface.jsonString()
        // The renderer consumes these exact keys (ts/lib/pgrep/manifold.ts Surface).
        for key in ["boundary", "spread", "bumps", "dips", "holes", "glows", "labels"] {
            XCTAssertTrue(json.contains("\"\(key)\""), "surface JSON missing \(key)")
        }
        // The encoder is lossless: it decodes back to an identical value.
        let decoded = try? JSONDecoder().decode(ManifoldSurface.self, from: Data(json.utf8))
        XCTAssertEqual(decoded, surface)
    }

    // MARK: Helpers

    /// A Memory result with the given per-category points; every other blueprint
    /// category abstains (no point), matching an unreviewed area.
    private func memoryResult(points: [String: Double]) -> MemoryResult {
        let byTopic = Blueprint.slugs.map { slug -> TopicScore in
            TopicScore(
                category: slug,
                blueprint: Blueprint.byCategory[slug]!,
                value: points[slug].map { scored($0) } ?? .abstaining("thin"),
                nCards: points[slug] == nil ? 0 : 10
            )
        }
        return MemoryResult(overall: .abstaining("thin"), byTopic: byTopic, kMem: 5, lastUpdated: nil)
    }

    /// A Performance result with the given per-category points; every other
    /// blueprint category abstains, matching a topic with too few attempts.
    private func performanceResult(points: [String: Double]) -> PerformanceResult {
        let byTopic = Blueprint.slugs.map { slug -> PerformanceTopic in
            PerformanceTopic(
                category: slug,
                blueprint: Blueprint.byCategory[slug]!,
                value: points[slug].map { scored($0) } ?? .abstaining("thin"),
                nAttempts: points[slug] == nil ? 0 : 10
            )
        }
        return PerformanceResult(overall: .abstaining("thin"), byTopic: byTopic, kPerf: 8, lastUpdated: nil)
    }

    private func scored(_ point: Double) -> ScoreValue {
        ScoreValue(point: point, low: point, high: point, abstain: false, reason: nil)
    }

    /// The bump, glow, hole, and dip an area contributed, located by the area's
    /// unique layout position (carried on every entry and its label).
    private func entries(
        _ surface: ManifoldSurface,
        _ topic: String
    ) -> (bump: ManifoldBump?, glow: ManifoldGlow?, hole: ManifoldHole?, dip: ManifoldBump?) {
        guard let label = surface.labels.first(where: { $0.topic == topic }) else {
            return (nil, nil, nil, nil)
        }
        let atArea: (Double, Double) -> Bool = { $0 == label.x && $1 == label.y }
        return (
            surface.bumps.first { atArea($0.x, $0.y) },
            surface.glows.first { atArea($0.x, $0.y) },
            surface.holes.first { atArea($0.x, $0.y) },
            surface.dips.first { atArea($0.x, $0.y) }
        )
    }
}
