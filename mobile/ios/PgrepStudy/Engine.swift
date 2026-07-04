// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Serial, off-main access to the shared Anki engine. AnkiBackend is not
// thread-safe, so every call runs on one private serial queue; a blocking call
// (a network sync can take seconds) therefore never freezes the UI. All results
// that cross back to callers are Sendable. This is the single seam the Home,
// Study, and Settings surfaces share, so they all drive one open collection.

import Foundation

enum EngineError: Error, CustomStringConvertible {
    case notOpen
    case noCurrentCard
    case badRating(Int)

    var description: String {
        switch self {
        case .notOpen: return "the collection is not open yet"
        case .noCurrentCard: return "there is no card to answer"
        case let .badRating(r): return "invalid rating \(r) (expected 1 to 4)"
        }
    }
}

/// A card ready to review, with everything the UI needs (no proto types leak).
struct ReviewCard: Sendable, Equatable {
    var cardId: Int64
    var front: String
    var back: String
    var remaining: Int
}

/// The outcome of a sync attempt.
enum SyncOutcome: Sendable, Equatable {
    /// A normal sync merged (or there was nothing to do), or a first-run full
    /// transfer completed automatically. Carries an optional server message.
    case completed(message: String?)
    /// Both sides diverged and a full sync is required; the user must choose a
    /// direction (upload or download).
    case conflictNeedsChoice
}

/// FSRS grade buttons, mapped to the engine's rating + next state.
enum Grade: Int, Sendable, CaseIterable {
    case again = 1
    case hard = 2
    case good = 3
    case easy = 4

    var label: String {
        switch self {
        case .again: return "Again"
        case .hard: return "Hard"
        case .good: return "Good"
        case .easy: return "Easy"
        }
    }
}

final class Engine: @unchecked Sendable {
    private let queue = DispatchQueue(label: "net.ankiweb.pgrep.engine")
    private var backend: AnkiBackend?
    // The card currently shown for review, kept here so proto types stay on the
    // engine's serial context and never cross an actor/task boundary.
    private var current: Anki_Scheduler_QueuedCards.QueuedCard?

    /// Open the backend and collection, and select the study deck. Must be
    /// called once before any other method.
    func open(collectionPath: String, mediaFolder: String) async throws {
        try await withCheckedThrowingContinuation { (cont: CheckedContinuation<Void, Error>) in
            queue.async {
                do {
                    let b = try AnkiBackend()
                    try b.openCollection(path: collectionPath, mediaFolder: mediaFolder)
                    try b.selectDeck(named: StudySandbox.studyDeckName)
                    self.backend = b
                    cont.resume(returning: ())
                } catch {
                    cont.resume(throwing: error)
                }
            }
        }
    }

    // MARK: Study (Cards door)

    /// Fetch the next queued card (points-at-stake order from the deck config),
    /// or nil when the queue is empty.
    func nextCard() async throws -> ReviewCard? {
        try await perform { backend in
            let queued = try backend.getQueuedCards(fetchLimit: 10)
            let remaining = Int(queued.newCount + queued.learningCount + queued.reviewCount)
            guard let first = queued.cards.first else {
                self.current = nil
                return nil
            }
            self.current = first
            let note = try backend.getNote(noteId: first.card.noteID)
            let front = note.fields.first ?? "(no front)"
            let back = note.fields.count > 1 ? note.fields[1] : "(no back)"
            return ReviewCard(cardId: first.card.id, front: front, back: back, remaining: remaining)
        }
    }

    /// Answer the current card with an FSRS grade. Real scheduling, real revlog;
    /// no scheduling state is mutated by hand.
    func answer(_ grade: Grade) async throws {
        try await perform { backend in
            guard let card = self.current else { throw EngineError.noCurrentCard }
            var answer = Anki_Scheduler_CardAnswer()
            answer.cardID = card.card.id
            answer.currentState = card.states.current
            switch grade {
            case .again:
                answer.newState = card.states.again
                answer.rating = .again
            case .hard:
                answer.newState = card.states.hard
                answer.rating = .hard
            case .good:
                answer.newState = card.states.good
                answer.rating = .good
            case .easy:
                answer.newState = card.states.easy
                answer.rating = .easy
            }
            answer.answeredAtMillis = Int64(Date().timeIntervalSince1970 * 1000)
            answer.millisecondsTaken = 1000
            try backend.answerCard(answer)
        }
    }

    // MARK: Home (Memory)

    /// Compute the native Memory score by folding the engine's own per-card FSRS
    /// retrievability over topic categories (identical primitive to desktop).
    func computeMemory() async throws -> MemoryResult {
        try await perform { backend in
            let cardIds = try backend.searchCards(matching: "tag:topic::*")
            var samples: [(category: String, r: Double)] = []
            var tagCache: [Int64: [String]] = [:]
            for cid in cardIds {
                let stats = try backend.cardStats(cardId: cid)
                // No FSRS state means new/unreviewed; excluded, exactly like the
                // desktop SQL (retrievability IS NULL).
                guard stats.hasFsrsRetrievability else { continue }
                let nid = stats.noteID
                let tags: [String]
                if let cached = tagCache[nid] {
                    tags = cached
                } else {
                    tags = try backend.getNote(noteId: nid).tags
                    tagCache[nid] = tags
                }
                samples.append((Topic.category(forTags: tags), Double(stats.fsrsRetrievability)))
            }
            return MemoryScore.fold(samples: samples)
        }
    }

    // MARK: Sync

    /// Log in to a self-hosted sync server and return the hkey to persist.
    func login(username: String, password: String, endpoint: String) async throws -> String {
        try await perform { backend in
            try backend.syncLogin(username: username, password: password, endpoint: endpoint).hkey
        }
    }

    /// Run a sync. First-run full up/downloads are handled automatically; a true
    /// divergence conflict is surfaced for the user to resolve.
    func sync(hkey: String, endpoint: String) async throws -> SyncOutcome {
        try await perform { backend in
            self.current = nil  // the queue may change; drop any stale card
            let auth = Self.auth(hkey: hkey, endpoint: endpoint)
            let res = try backend.syncCollection(auth: auth)
            switch res.required {
            case .noChanges, .normalSync:
                return .completed(message: res.serverMessage.isEmpty ? nil : res.serverMessage)
            case .fullUpload:
                try backend.fullUploadOrDownload(auth: auth, upload: true)
                return .completed(message: "Uploaded to the server.")
            case .fullDownload:
                try backend.fullUploadOrDownload(auth: auth, upload: false)
                // A full download replaces the collection, resetting the current
                // deck; re-select the study deck so Study keeps its queue.
                try? backend.selectDeck(named: StudySandbox.studyDeckName)
                return .completed(message: "Downloaded from the server.")
            case .fullSync, .UNRECOGNIZED:
                return .conflictNeedsChoice
            }
        }
    }

    /// Resolve a full-sync conflict in an explicit direction.
    func resolveConflict(hkey: String, endpoint: String, upload: Bool) async throws {
        try await perform { backend in
            self.current = nil
            try backend.fullUploadOrDownload(auth: Self.auth(hkey: hkey, endpoint: endpoint), upload: upload)
            if !upload {
                try? backend.selectDeck(named: StudySandbox.studyDeckName)
            }
        }
    }

    // MARK: - Plumbing

    private static func auth(hkey: String, endpoint: String) -> Anki_Sync_SyncAuth {
        var auth = Anki_Sync_SyncAuth()
        auth.hkey = hkey
        auth.endpoint = endpoint
        return auth
    }

    /// Run `work` on the serial engine queue, bridging to async. Results are
    /// Sendable so they cross back safely.
    private func perform<T: Sendable>(_ work: @escaping @Sendable (AnkiBackend) throws -> T) async throws -> T {
        try await withCheckedThrowingContinuation { cont in
            queue.async {
                do {
                    guard let backend = self.backend else { throw EngineError.notOpen }
                    cont.resume(returning: try work(backend))
                } catch {
                    cont.resume(throwing: error)
                }
            }
        }
    }
}
