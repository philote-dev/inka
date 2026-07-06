// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// The attempt log, read-only, for the iOS companion. The desktop stores each
// problem/exam attempt as one immutable Anki note (notetype "pgrep::Attempt",
// tag "pgrep::attempt"), riding Anki's free note sync (see
// pylib/anki/pgrep/attempt_log.py, "notes-as-log"). Because those are ordinary
// synced notes, the phone can read exactly what desktop wrote once it syncs, and
// fold them into Performance and Readiness with no custom SQL, proto, or Rust.
//
// This file is the read side: it parses an attempt note's `event_json` blob into
// the typed fields the Performance fold needs. The WRITE side now lives in
// AttemptWriter.swift (note-add + notetype/deck bootstrap over FFI), so a
// phone-run exam or ladder persists attempts here that then sync to desktop. On
// a phone that has never recorded or synced problem work the attempt log is
// simply empty, and Performance/Readiness abstain honestly for the right reason
// (insufficient attempt data), never a fabricated number.

import Foundation

/// Schema constants for the immutable attempt-log notes. Mirrors
/// pylib/anki/pgrep/attempt_log.py. Duplicated across the language boundary on
/// purpose (the L1 contract), not shared.
enum AttemptLog {
    /// The attempt notetype name (identity of an attempt note on desktop).
    static let notetypeName = "pgrep::Attempt"
    /// Every attempt note carries this tag (the K3 cheap pre-filter).
    static let tag = "pgrep::attempt"
    /// Field order is (event_id, event_json, topic, correct, answered_at); the
    /// self-contained JSON blob the fold reads lives in field index 1.
    static let eventJsonFieldIndex = 1
    /// Anki search that returns every attempt note (tag pre-filter, like the
    /// desktop read-model seam scans the notetype).
    static let search = "tag:\(tag)"
}

/// One attempt event with the typed fields the Performance fold needs, parsed
/// from an attempt note's `event_json`. A faithful subset of
/// attempt_log.Event, with performance._attempt_difficulty's word/number
/// mapping applied at parse time so the fold itself stays pure numerics.
struct AttemptEvent: Sendable, Equatable {
    var eventId: String
    /// Blueprint category slug (payload `category`, else derived from `topic`).
    var category: String
    var correct: Bool
    /// Epoch seconds; the fold sorts oldest-first so the recency window is right.
    var answeredAt: Int
    /// Ladder depth (0 == a clean, committed, first-try attempt).
    var ladderDepth: Int
    /// Client-measured response time in ms, if logged (M5 data-quality signal).
    var responseMs: Double?
    /// Authored difficulty on the 1..5 scale, if the payload carried one.
    var difficulty: Double?
    /// The attempted item's note id, if present (drives the distinct-items count).
    var itemNoteId: Int64?

    /// Whether this attempt counts toward the score (performance._is_clean):
    /// only clean, committed, first-try attempts (ladder_depth == 0) that are not
    /// rapid guesses. Missing fields are treated as clean.
    func isClean(minResponseMs: Double) -> Bool {
        if ladderDepth != 0 { return false }
        if let responseMs, responseMs < minResponseMs { return false }
        return true
    }
}

/// Parses `event_json` blobs into `AttemptEvent`s. Kept separate from the fold
/// so the numeric coercions (the one place JSON's dynamism leaks in) are
/// isolated and testable.
enum AttemptParser {
    /// Authored difficulty words -> the 1..5 scale (performance._DIFFICULTY_LABELS).
    static let difficultyLabels: [String: Double] = [
        "very_easy": 1.0,
        "easy": 2.0,
        "medium": 3.0,
        "hard": 4.0,
        "very_hard": 5.0,
    ]

    /// Parse a raw `event_json` string. Returns nil for a blob that does not
    /// decode to a JSON object, matching the desktop fold, which skips a
    /// malformed note rather than letting it sink the whole fold.
    static func parse(_ json: String) -> AttemptEvent? {
        guard let data = json.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data),
              let dict = object as? [String: Any]
        else { return nil }
        return parse(dict)
    }

    static func parse(_ dict: [String: Any]) -> AttemptEvent? {
        let topic = nonEmptyString(dict["topic"])
        let category = nonEmptyString(dict["category"])
            ?? Topic.category(forTags: topic.map { [$0] } ?? [])
        return AttemptEvent(
            eventId: nonEmptyString(dict["event_id"]) ?? "",
            category: category,
            correct: boolValue(dict["correct"]),
            answeredAt: intValue(dict["answered_at"]) ?? 0,
            ladderDepth: intValue(dict["ladder_depth"]) ?? 0,
            responseMs: numberValue(dict["response_ms"]),
            difficulty: difficultyValue(dict["difficulty"]),
            itemNoteId: int64Value(dict["item_note_id"])
        )
    }

    // MARK: - Coercions

    /// True only for a JSON boolean. JSONSerialization represents JSON
    /// true/false as CFBoolean, so this is an exact, non-ambiguous test (a plain
    /// numeric 0/1 is not treated as a bool).
    private static func isJSONBool(_ value: Any?) -> Bool {
        guard let value else { return false }
        return CFGetTypeID(value as CFTypeRef) == CFBooleanGetTypeID()
    }

    private static func boolValue(_ value: Any?) -> Bool {
        if isJSONBool(value), let number = value as? NSNumber { return number.boolValue }
        return false
    }

    private static func nonEmptyString(_ value: Any?) -> String? {
        guard let string = value as? String, !string.isEmpty else { return nil }
        return string
    }

    private static func intValue(_ value: Any?) -> Int? {
        if isJSONBool(value) { return nil }
        if let number = value as? NSNumber { return number.intValue }
        if let string = value as? String { return Int(string) }
        return nil
    }

    private static func int64Value(_ value: Any?) -> Int64? {
        if isJSONBool(value) { return nil }
        if let number = value as? NSNumber { return number.int64Value }
        if let string = value as? String { return Int64(string) }
        return nil
    }

    private static func numberValue(_ value: Any?) -> Double? {
        if isJSONBool(value) { return nil }
        if let number = value as? NSNumber { return number.doubleValue }
        if let string = value as? String { return Double(string) }
        return nil
    }

    /// The item's authored difficulty (1..5) from the payload, or nil when
    /// absent/unparseable (performance._attempt_difficulty). A number is clamped
    /// to 1..5; a word is mapped; anything else is nil so the fold falls back to
    /// a neutral difficulty. In practice this arrives as a string (the Problem
    /// difficulty field is stored as text like "3.00").
    private static func difficultyValue(_ value: Any?) -> Double? {
        guard let value, !isJSONBool(value) else { return nil }
        if let string = value as? String {
            let key = string.trimmingCharacters(in: .whitespaces).lowercased()
            if let mapped = difficultyLabels[key] { return mapped }
            if let number = Double(key) { return clampDifficulty(number) }
            return nil
        }
        if let number = value as? NSNumber { return clampDifficulty(number.doubleValue) }
        return nil
    }

    private static func clampDifficulty(_ value: Double) -> Double {
        value < 1.0 ? 1.0 : (value > 5.0 ? 5.0 : value)
    }
}
