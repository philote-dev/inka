// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// The attempt-log WRITE path for the iOS companion (the counterpart to the
// read-only AttemptLog.swift). Desktop stores each problem/exam attempt as one
// immutable Anki note (notetype "pgrep::Attempt", tag "pgrep::attempt") that
// rides Anki's free note sync (pylib/anki/pgrep/attempt_log.py, "notes-as-log").
// This file lets the phone WRITE those same notes over the FFI, so a phone-run
// exam or wrong-answer ladder persists attempts that then sync to desktop and
// feed Performance/Readiness, on either device, through the identical fold.
//
// It mirrors attempt_log.append_attempt exactly:
//   - ensure the pgrep::Attempt notetype (find the synced one first; only create
//     it, schema-identical to desktop, on a never-synced phone) so an iOS note
//     and a desktop note are the same kind of note and merge on sync;
//   - ensure the suspended, hidden pgrep::attempt-log deck;
//   - add one immutable note per attempt (guid == event_id, K2), its event_json
//     the self-contained payload the fold reads (K1), then suspend its card.
//
// Honesty: only clean, real attempts are ever handed here (ladder_depth 0,
// committed before any help); nothing is fabricated. This is the WRITE half of
// the L5.2 seam whose absence AttemptLog.swift / ExamScore.swift noted as a TODO.

import Foundation

/// Write-side schema for the immutable attempt-log notes. Mirrors
/// pylib/anki/pgrep/attempt_log.py. The notetype name / tag intentionally mirror
/// the read-side constants in AttemptLog.swift; they are duplicated here so the
/// write path is self-contained (and unit-testable without the read model).
enum AttemptSchema {
    /// The attempt notetype name (identity of an attempt note on desktop).
    static let notetypeName = "pgrep::Attempt"
    /// Every attempt note carries this tag (the cheap tag pre-filter).
    static let tag = "pgrep::attempt"
    /// Attempt cards live suspended in this hidden deck (kept out of study).
    static let deckName = "pgrep::attempt-log"
    /// The event-schema version stamped into every payload.
    static let schemaVersion = 1
    /// Field order (fixed by the L1 contract); `event_id` is the sort field.
    static let fields = ["event_id", "event_json", "topic", "correct", "answered_at"]
    /// The single, never-shown card template Anki requires.
    static let templateName = "Attempt"
    static let templateQfmt = "{{event_id}}"
    static let templateAfmt = "{{event_json}}"

    /// Serialize a payload to the stored `event_json` string. `sortedKeys`
    /// mirrors desktop's `json.dumps(..., sort_keys=True)`; JSONSerialization
    /// emits UTF-8 without escaping non-ASCII (matching `ensure_ascii=False`).
    static func encode(_ payload: [String: Any]) throws -> String {
        let data = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
        return String(decoding: data, as: UTF8.self)
    }
}

/// One clean, committed attempt to persist. The caller builds one per answered
/// exam question or committed ladder problem; the writer turns it into an
/// immutable note. The payload shape matches desktop's commit_problem event
/// (plus the canonical fields _build_payload guarantees), so the SAME fold reads
/// iOS-written and desktop-written attempts identically.
struct AttemptDraft: Sendable, Equatable {
    /// The attempted item's note id (drives the distinct-items coverage signal).
    var itemNoteId: Int64
    /// The finest topic tag verbatim (e.g. "topic::mechanics"), or nil.
    var topic: String?
    /// The blueprint category slug (e.g. "mechanics"); what the fold buckets on.
    var category: String
    var correct: Bool
    /// The letter the learner committed (A..E); recorded, not scored.
    var selectedOption: String
    /// Groups the attempts from one sitting (a fresh UUID per exam/ladder run).
    var sessionId: String
    /// Epoch seconds when the answer was committed.
    var answeredAt: Int
    /// Ladder depth; 0 for a clean, committed, first-try answer.
    var ladderDepth: Int
    /// Authored difficulty on the 1..5 scale, if known.
    var difficulty: Double?
    /// Client-measured think time (ms) from item shown to commit, if measured.
    /// Left off when unmeasured, which the clean rule treats as clean.
    var responseMs: Int?

    /// The self-contained JSON payload, with the canonical fields desktop's
    /// `_build_payload` fills in. `eventId` becomes the note guid (K2).
    func payload(eventId: String) -> [String: Any] {
        var payload: [String: Any] = [
            "event_id": eventId,
            "schema": AttemptSchema.schemaVersion,
            "item_note_id": itemNoteId,
            "topic": topic ?? NSNull(),
            "category": category,
            "correct": correct,
            "selected_option": selectedOption,
            "session_id": sessionId,
            "answered_at": answeredAt,
            "ladder_depth": ladderDepth,
        ]
        if let difficulty { payload["difficulty"] = difficulty }
        if let responseMs { payload["response_ms"] = responseMs }
        return payload
    }
}

extension AnkiBackend {
    /// The `pgrep::Attempt` notetype id, creating it (schema-identical to
    /// desktop) only when a never-synced phone lacks it. Mirrors
    /// attempt_log.ensure_attempt_notetype. The common case (a phone that synced
    /// from desktop) finds the existing notetype and creates nothing, so the two
    /// devices share one notetype and their notes merge on sync.
    func ensureAttemptNotetype() throws -> Int64 {
        let existing = try notetypeId(forName: AttemptSchema.notetypeName)
        if existing != 0 { return existing }

        var notetype = Anki_Notetypes_Notetype()
        notetype.name = AttemptSchema.notetypeName
        var config = Anki_Notetypes_Notetype.Config()
        config.kind = .normal
        config.sortFieldIdx = 0
        notetype.config = config
        notetype.fields = AttemptSchema.fields.map { name in
            var field = Anki_Notetypes_Notetype.Field()
            field.name = name
            return field
        }
        var template = Anki_Notetypes_Notetype.Template()
        template.name = AttemptSchema.templateName
        template.config.qFormat = AttemptSchema.templateQfmt
        template.config.aFormat = AttemptSchema.templateAfmt
        notetype.templates = [template]
        return try addNotetype(notetype)
    }

    /// The suspended, hidden `pgrep::attempt-log` deck id (created, with its
    /// parent, if missing). Mirrors attempt_log.ensure_attempt_deck.
    func ensureAttemptDeck() throws -> Int64 {
        let existing = try deckId(forName: AttemptSchema.deckName)
        if existing != 0 { return existing }
        var deck = try newDeck()
        deck.name = AttemptSchema.deckName
        return try addDeck(deck)
    }

    /// Append one immutable attempt note and suspend its card, exactly like
    /// desktop's append_attempt. Returns the event_id (== note guid). The
    /// notetype/deck ids are passed in so a batch resolves them once.
    @discardableResult
    func appendAttempt(_ draft: AttemptDraft, notetypeId: Int64, deckId: Int64) throws -> String {
        let eventId = UUID().uuidString
        let json = try AttemptSchema.encode(draft.payload(eventId: eventId))

        var note = Anki_Notes_Note()
        note.notetypeID = notetypeId
        // K2: force the note guid to equal the event_id.
        note.guid = eventId
        note.fields = [
            eventId,
            json,
            draft.topic ?? "",
            draft.correct ? "1" : "0",
            String(draft.answeredAt),
        ]
        note.tags = [AttemptSchema.tag] + (draft.topic.map { [$0] } ?? [])

        let response = try addNote(note, deckId: deckId)
        try suspendCards(noteIds: [response.noteID])
        return eventId
    }

    /// Ensure the notetype + deck once, then append every draft. Returns the
    /// event_ids written. Empty input is a no-op (writes nothing).
    @discardableResult
    func appendAttempts(_ drafts: [AttemptDraft]) throws -> [String] {
        guard !drafts.isEmpty else { return [] }
        let notetypeId = try ensureAttemptNotetype()
        let deckId = try ensureAttemptDeck()
        return try drafts.map { try appendAttempt($0, notetypeId: notetypeId, deckId: deckId) }
    }
}
