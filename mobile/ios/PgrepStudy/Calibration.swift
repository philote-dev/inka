// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// The calibration gate status, a faithful port of pylib/anki/pgrep/calibration.py.
// Calibration is the generation-effect act: the learner writes one card in their
// own words for each blueprint category. A collection is calibrated once it has at
// least one learner-authored card (CardSets.seedTag) in every blueprint category,
// or once the sticky "complete" flag has been recorded. The flag makes calibration
// durable, so removing an authored card later never re-locks it. Only
// learner-authored cards count; the bundled sample cards calibrate nothing.
//
// On desktop the gate bites only while AI is on (aiEnabled && !calibrated): Study
// locks and Library forces the walkthrough. This app is AI off by construction, so
// the gate never bites here: Study is never blocked and the walkthrough is a
// voluntary "Teach pgrep your style" entry. This file is the pure, testable core
// (the covered-category and status derivation) plus the note + config read/write
// extension, split like CardSets / Diagnostic so the host-less test bundle can pin
// the derivation without a running engine.

import Foundation

/// The calibration status, matching the shape of calibration.calibration_status:
/// how many blueprint categories the learner has authored a card in (`authored`),
/// how many there are (`required`), and whether that calibrates the collection.
struct CalibrationStatus: Sendable, Equatable {
    let calibrated: Bool
    let authored: Int
    let required: Int
    /// Whether the caller should now record the sticky "calibrated" flag: true
    /// exactly when the flag is not yet stored but the collection just reached
    /// full coverage. An internal signal for the durable write (mirrors the
    /// set-on-completion in calibration_status), not part of the JSON status.
    var shouldPersist = false
}

/// Pure, testable core for the calibration gate (no SwiftUI, no engine).
enum Calibration {
    /// Sticky "calibration complete" flag in the collection config. Must equal
    /// calibration.CALIBRATION_CONFIG_KEY so a phone-set completion syncs to the
    /// desktop (and vice versa). Once set, it stays set.
    static let configKey = "pgrepCalibrated"

    /// The learner-authored marker tag counted for calibration. Reuses
    /// CardSets.seedTag (generation.SEED_TAG), distinct from the seeder's
    /// pgrep::seeded, so only learner-authored cards calibrate.
    static let seedTag = CardSets.seedTag

    /// One learner-authored card per blueprint category calibrates the
    /// collection. Mirrors calibration.REQUIRED_CATEGORIES (len(CATEGORY_SLUGS)).
    static let requiredCategories = Blueprint.slugs.count

    /// The Anki search that finds the learner-authored candidate notes. Mirrors
    /// calibration._covered_categories' `find_notes(f"tag:{SEED_TAG}")`.
    static var searchQuery: String { "tag:\(seedTag)" }

    /// The blueprint categories with at least one learner-authored card. A port
    /// of calibration._covered_categories: read each authored note's category
    /// (first topic tag wins) and keep the ones that are recognized blueprint
    /// slugs. `tagLists` is one tag array per learner-authored note.
    static func coveredCategories(fromTagLists tagLists: [[String]]) -> Set<String> {
        var covered: Set<String> = []
        for tags in tagLists {
            let category = Topic.category(forTags: tags)
            if Blueprint.byCategory[category] != nil {
                covered.insert(category)
            }
        }
        return covered
    }

    /// Derive the calibration status from the authored count and the stored
    /// sticky flag. A port of calibration.calibration_status' derivation:
    /// `calibrated` is true once every category is covered OR the sticky flag is
    /// already set, and `shouldPersist` signals the set-on-completion write (the
    /// flag is not yet stored but full coverage was just reached), so calibration
    /// becomes durable and survives a later card deletion.
    static func status(authored: Int, storedCalibrated: Bool) -> CalibrationStatus {
        let reached = authored >= requiredCategories
        return CalibrationStatus(
            calibrated: storedCalibrated || reached,
            authored: authored,
            required: requiredCategories,
            shouldPersist: !storedCalibrated && reached
        )
    }
}

extension AnkiBackend {
    /// Read the calibration gate status, a port of calibration.calibration_status
    /// over the note + config RPCs: count the blueprint categories with a
    /// learner-authored (CardSets.seedTag) card, read the sticky "calibrated"
    /// flag, and set it on first completion so calibration is durable. Only
    /// learner-authored cards count, so a fresh (seeded-only) collection is
    /// honestly uncalibrated. No AI, no scheduler.
    func calibrationStatus() throws -> CalibrationStatus {
        let noteIds = try searchNotes(matching: Calibration.searchQuery)
        var tagLists: [[String]] = []
        tagLists.reserveCapacity(noteIds.count)
        for nid in noteIds {
            tagLists.append(try getNote(noteId: nid).tags)
        }
        let authored = Calibration.coveredCategories(fromTagLists: tagLists).count
        let status = Calibration.status(
            authored: authored,
            storedCalibrated: try calibrationFlag()
        )
        if status.shouldPersist {
            // Set-on-completion: record the durable flag so a later card deletion
            // never re-locks calibration (mirrors col.set_config on completion).
            try setConfigJson(key: Calibration.configKey, valueJson: Data("true".utf8))
        }
        return status
    }

    /// The stored sticky "calibrated" flag (Calibration.configKey), false when
    /// unset. The value is a JSON bool in the synced collection config, the same
    /// key and shape the desktop writes, so a completion carries across hosts.
    private func calibrationFlag() throws -> Bool {
        guard let data = try getConfigJson(key: Calibration.configKey), !data.isEmpty else {
            return false
        }
        let value = try? JSONSerialization.jsonObject(with: data, options: [.fragmentsAllowed])
        return (value as? Bool) ?? false
    }
}
