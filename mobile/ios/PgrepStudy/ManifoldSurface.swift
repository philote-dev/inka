// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// The knowledge-manifold surface for the native Home hero, a faithful port of
// the desktop read model in pylib/anki/pgrep/manifold.py. The nine exam areas
// always sit on the map (the syllabus exists), but the terrain is the learner's
// real Memory: a studied area rises and lights amber, an area whose Memory has
// dropped below a floor opens a hole (a known gap), and a fresh collection is a
// gentle, even, unlit syllabus with no peaks, glows, or holes. Nothing here
// fabricates a number; the terrain is the same Memory primitive the score cards
// read, so the map and the Memory card never disagree.
//
// The value is Codable to exactly the `Surface` JSON the WebGL renderer consumes
// (ts/lib/pgrep/manifold.ts), so the native Home feeds the same real 3D manifold
// the desktop web Home draws (hosted in a WKWebView, see ManifoldWebView).
//
// The layout and terrain constants are duplicated here on purpose, the same
// deliberate cross-language boundary duplication the desktop keeps between its
// Python read model and the TS renderer. Do not factor these into a shared,
// synced source.
//
// Note: the desktop also folds in the stored diagnostic placement (a
// diagnostic-strong area half-lights, a rusty one opens a hole). The native
// Diagnostic flow is not yet ported, so this surface is driven by Memory alone;
// once a topic has reviews, the two agree.

import Foundation

/// One raised (or dipped) area of the surface. Matches the TS `Bump`.
struct ManifoldBump: Codable, Equatable {
    var x: Double
    var y: Double
    var h: Double
    var s: Double
}

/// A real gap punched through the mesh. Matches the TS `Hole`.
struct ManifoldHole: Codable, Equatable {
    var x: Double
    var y: Double
    var rx: Double
    var ry: Double
    var rot: Double
}

/// A soft floor under-glow in a reserved score hue. Matches the TS `Glow`.
struct ManifoldGlow: Codable, Equatable {
    var x: Double
    var y: Double
    var c: String
}

/// A topic label anchor. Matches the TS `ManifoldLabel`.
struct ManifoldLabel: Codable, Equatable {
    var name: String
    var x: Double
    var y: Double
    var dx: Double
    var dy: Double
    var tf: String
    var topic: String
}

/// The full data-driven surface, Codable to the exact JSON `Surface` shape the
/// renderer consumes (`boundary`, `spread`, `bumps`, `dips`, `holes`, `glows`,
/// `labels`).
struct ManifoldSurface: Codable, Equatable {
    var boundary: [Double]
    var spread: Double
    var bumps: [ManifoldBump]
    var dips: [ManifoldBump]
    var holes: [ManifoldHole]
    var glows: [ManifoldGlow]
    var labels: [ManifoldLabel]

    // MARK: Layout (fixed) and terrain tuning (mirrors manifold.py)

    /// Where each exam area sits on the map and how its label is offset. Mirrors
    /// `_LAYOUT` in manifold.py (the design's fixed placement).
    private struct Area {
        let topic: String
        let name: String
        let x: Double
        let y: Double
        let dx: Double
        let dy: Double
        let tf: String
    }

    private static let layout: [Area] = [
        Area(topic: "mechanics", name: "Classical Mechanics", x: -0.6, y: -0.5, dx: -60, dy: -44, tf: "translate(-100%, -100%)"),
        Area(topic: "electromagnetism", name: "Electromagnetism", x: 0.56, y: -0.48, dx: 30, dy: -60, tf: "translate(0, -100%)"),
        Area(topic: "optics_waves", name: "Optics & Waves", x: 1.0, y: -0.14, dx: 54, dy: -22, tf: "translate(0, -100%)"),
        Area(topic: "thermodynamics", name: "Thermo & Stat Mech", x: -1.05, y: 0.14, dx: -54, dy: 26, tf: "translate(-100%, 0)"),
        Area(topic: "quantum", name: "Quantum Mechanics", x: 0.16, y: 0.6, dx: -60, dy: 190, tf: "translate(-100%, 0)"),
        Area(topic: "atomic", name: "Atomic Physics", x: 0.72, y: 0.4, dx: 64, dy: 46, tf: "translate(0, 0)"),
        Area(topic: "special_relativity", name: "Special Relativity", x: -0.56, y: 0.62, dx: -50, dy: 62, tf: "translate(-100%, 0)"),
        Area(topic: "lab", name: "Laboratory Methods", x: -0.05, y: -0.62, dx: 10, dy: -60, tf: "translate(-50%, -100%)"),
        Area(topic: "specialized", name: "Specialized Topics", x: 0.16, y: 0.04, dx: 30, dy: 195, tf: "translate(0, 0)"),
    ]

    // Map frame (copied from the renderer's FULL_SURFACE) and terrain tuning,
    // matching manifold.py so the native map keeps the same silhouette + rules.
    private static let boundaryConst: [Double] = [1.12, 0.09, 2.6, 0.2, 0.55]
    private static let spreadConst = 0.42
    private static let memoryHue = "235,203,139"
    private static let baseHeight = 0.16
    private static let masteryGain = 0.5
    private static let baseSpread = 0.28
    private static let weakMemory = 0.45

    /// Build the surface from the live Memory fold, exactly like desktop's
    /// `manifold_surface`: an untouched area is a gentle unlit base, a studied
    /// area rises and glows amber, a known-weak area (Memory below the floor)
    /// opens a hole. Passing a Memory that abstains everywhere yields the honest
    /// unlit syllabus (no glows, no holes).
    static func build(memory: MemoryResult) -> ManifoldSurface {
        var pointByCategory: [String: Double] = [:]
        for topic in memory.byTopic {
            if let point = topic.value.point {
                pointByCategory[topic.category] = point
            }
        }

        var bumps: [ManifoldBump] = []
        var dips: [ManifoldBump] = []
        var holes: [ManifoldHole] = []
        var glows: [ManifoldGlow] = []
        var labels: [ManifoldLabel] = []

        for area in layout {
            let point = pointByCategory[area.topic]
            var height = baseHeight
            var lit = false
            if let point {
                height = baseHeight + masteryGain * point
                lit = true
            }

            bumps.append(ManifoldBump(x: area.x, y: area.y, h: height, s: baseSpread))
            if lit {
                glows.append(ManifoldGlow(x: area.x, y: area.y, c: memoryHue))
            }

            if let point, point < weakMemory {
                holes.append(ManifoldHole(x: area.x, y: area.y, rx: 0.16, ry: 0.1, rot: 0.0))
                dips.append(ManifoldBump(x: area.x, y: area.y, h: 0.12, s: 0.26))
            }

            labels.append(ManifoldLabel(
                name: area.name,
                x: area.x,
                y: area.y,
                dx: area.dx,
                dy: area.dy,
                tf: area.tf,
                topic: area.topic
            ))
        }

        return ManifoldSurface(
            boundary: boundaryConst,
            spread: spreadConst,
            bumps: bumps,
            dips: dips,
            holes: holes,
            glows: glows,
            labels: labels
        )
    }

    /// The honest unlit syllabus: nine even bases, no glows or holes. Used before
    /// the first scoreboard read so the hero is never blank.
    static var baseline: ManifoldSurface {
        build(memory: MemoryResult(overall: .abstaining("loading"), byTopic: [], kMem: MemoryScore.kMemDefault, lastUpdated: nil))
    }

    /// The surface serialized to the JSON the renderer consumes.
    func jsonString() -> String {
        let encoder = JSONEncoder()
        guard let data = try? encoder.encode(self), let json = String(data: data, encoding: .utf8) else {
            return "{}"
        }
        return json
    }
}
