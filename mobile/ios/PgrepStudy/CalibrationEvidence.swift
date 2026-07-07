// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Embedded model-calibration evidence (aggregate statistics, constants only), a
// faithful port of pylib/anki/pgrep/calibration_evidence.py. The honest Progress
// dashboard shows each of the two model layers with its calibration evidence: a
// reliability diagram (predicted vs observed points) plus a Brier score. Those
// numbers come from offline evaluations on held-out data:
//
//   - Memory is default FSRS-6 retrievability against actual recall on held-out
//     reviews (L5.1). pgrep serves raw FSRS R, so the honest curve is the default
//     one, slightly overconfident.
//   - Performance is P(correct) against held-out exam-style outcomes (L5.2). The
//     synthetic study validates the pipeline and methodology, not a real cohort.
//
// Like the ported Diagnostic.quickChecks constant, this embeds those results as
// tracked constants: aggregate statistics (binned reliability points and a Brier
// score) that are plain factual measurements, not the private source data. The
// private content/ tree is absent in the shipped app, so nothing on the
// calibration path reads it at runtime. Mirrors the desktop pgrep_calibration
// handler, which returns this embedded evidence with no collection read.

import Foundation

/// One reliability point as the embedded evidence stores it, mirroring the
/// `{p, o}` JSON shape produced by calibration_evidence.py. Codable so the shape
/// maps one-to-one to that payload; `reliabilityPoint` is the bridge to
/// ReliabilityDiagramView's `{predicted, observed}` input (the reviewer of
/// ReliabilityDiagramView flagged that this bridge is needed, since the diagram
/// spells the keys out while the evidence uses the compact `p`/`o`).
struct CalibrationPoint: Codable, Equatable {
    /// Predicted probability, 0..1 (the diagram's x axis).
    let p: Double
    /// Observed outcome rate, 0..1 (the diagram's y axis).
    let o: Double

    /// Map to the diagram's spelled-out point shape.
    var reliabilityPoint: ReliabilityPoint {
        ReliabilityPoint(predicted: p, observed: o)
    }
}

/// One model layer's calibration evidence, matching a layer of
/// calibration_evidence.py's output: the reliability `points`, the `brier`
/// score, the sample `n`, a short honest `note` (the caption), and the
/// provenance (`source`, `method`, `date`).
struct CalibrationLayer: Codable, Equatable {
    let points: [CalibrationPoint]
    let brier: Double
    let n: Int
    let note: String
    let source: String
    let method: String
    let date: String

    /// The reliability points mapped to ReliabilityDiagramView's input shape.
    var reliabilityPoints: [ReliabilityPoint] {
        points.map(\.reliabilityPoint)
    }
}

/// The embedded calibration evidence for the two model layers, matching
/// calibration_evidence.py's `{"memory": {...}, "performance": {...}}`.
struct CalibrationEvidence: Codable, Equatable {
    let memory: CalibrationLayer
    let performance: CalibrationLayer

    /// The embedded evidence, ported verbatim from calibration_evidence.py.
    /// Regenerate the numbers there (never hand-edit) if an offline re-run
    /// changes them, and mirror the update here.
    static let embedded = CalibrationEvidence(
        // --- Memory: default FSRS-6 on held-out reviews (L5.1) ---
        memory: CalibrationLayer(
            points: [
                CalibrationPoint(p: 0.5537578246385091, o: 0.31025299600532624),
                CalibrationPoint(p: 0.6818266360154652, o: 0.5446071904127829),
                CalibrationPoint(p: 0.7481109235814282, o: 0.596537949400799),
                CalibrationPoint(p: 0.8029890985095504, o: 0.708),
                CalibrationPoint(p: 0.8379842805075447, o: 0.7653333333333333),
                CalibrationPoint(p: 0.8648675644832492, o: 0.7546666666666667),
                CalibrationPoint(p: 0.8875462455797204, o: 0.756),
                CalibrationPoint(p: 0.9106683994243087, o: 0.7786666666666666),
                CalibrationPoint(p: 0.9392564305080099, o: 0.7386666666666667),
                CalibrationPoint(p: 0.9798395923438424, o: 0.668),
            ],
            brier: 0.23376769284759738,
            n: 7503,
            note: "Validated on held-out reviews. Default FSRS, slightly overconfident.",
            source: "Held-out reviews from the anki-revlogs-10k sample (4 users, time-split)",
            method: "Default FSRS-6 (fsrs-rs 5.2.0) retrievability vs recall; binning-free Brier",
            date: "2026-07-05"
        ),
        // --- Performance: held-out synthetic pipeline validation (L5.2) ---
        performance: CalibrationLayer(
            points: [
                CalibrationPoint(p: 0.42041089306686397, o: 0.3125),
                CalibrationPoint(p: 0.6417704111662867, o: 0.75),
                CalibrationPoint(p: 0.7552744918905231, o: 0.625),
                CalibrationPoint(p: 0.8183745451592563, o: 0.75),
                CalibrationPoint(p: 0.8628029972318318, o: 0.8125),
                CalibrationPoint(p: 0.8898958087171822, o: 0.9375),
                CalibrationPoint(p: 0.9184974003972319, o: 0.9375),
                CalibrationPoint(p: 0.9331065135300922, o: 0.75),
                CalibrationPoint(p: 0.946382250923898, o: 0.6875),
                CalibrationPoint(p: 0.9597583033785975, o: 0.875),
            ],
            brier: 0.17523368467276343,
            n: 160,
            note: "Methodology validated on held-out synthetic (n=1 cohort).",
            source: "Held-out synthetic exam-style outcomes (pipeline validation)",
            method: "PFA logistic + beta calibration on a held-out split; binning-free Brier",
            date: "2026-07-05"
        )
    )
}
