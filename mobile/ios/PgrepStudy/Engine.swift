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

/// The four pgrep read-outs, computed together in one engine pass so Home and
/// Progress share a single consistent snapshot (Memory feeds Performance and
/// Coverage; Performance feeds Readiness), exactly like desktop composes them.
struct Scoreboard: Sendable, Equatable {
    var memory: MemoryResult
    var performance: PerformanceResult
    var readiness: ReadinessResult
    var coverage: CoverageResult
    /// The stored diagnostic placement (strong/rusty per category), so the Home
    /// manifold can fold it into the terrain exactly like desktop. Empty when the
    /// Diagnostic has never run, so the map degrades to the Memory terrain.
    var placement: [String: DiagnosticPlacement]
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

    // MARK: Home (the three scores)

    /// Compute the native Memory score by folding the engine's own per-card FSRS
    /// retrievability over topic categories (identical primitive to desktop).
    func computeMemory() async throws -> MemoryResult {
        try await perform { backend in
            try Engine.memoryResult(backend)
        }
    }

    /// Compute all three honest scores plus coverage in one engine pass, exactly
    /// how desktop composes them: Memory folds FSRS retrievability; Performance
    /// folds the attempt log with Memory as the mastery bridge; Readiness
    /// projects the scaled score from Performance; Coverage is the reviewed-card
    /// ledger over Memory. With no attempt data (a phone that has not synced
    /// problem work), Performance and Readiness abstain honestly for the right
    /// reason rather than showing a fabricated number.
    func computeScoreboard() async throws -> Scoreboard {
        try await perform { backend in
            let now = Date()
            let memory = try Engine.memoryResult(backend, now: now)
            let events = try Engine.attemptEvents(backend)
            let performance = PerformanceScore.compute(
                events: events,
                masteryByCategory: memory.masteryByCategory,
                now: now
            )
            let readiness = ReadinessScore.compute(performance: performance)
            let coverage = CoverageScore.compute(memory: memory)
            let placement = try Engine.diagnosticPlacement(backend)
            return Scoreboard(
                memory: memory,
                performance: performance,
                readiness: readiness,
                coverage: coverage,
                placement: placement
            )
        }
    }

    /// Fold the Memory score from the engine's per-card FSRS retrievability.
    /// Static so both `computeMemory` and `computeScoreboard` share one pass and
    /// proto types stay on the engine's serial context.
    private static func memoryResult(_ backend: AnkiBackend, now: Date = Date()) throws -> MemoryResult {
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
        return MemoryScore.fold(samples: samples, now: now)
    }

    /// Read every immutable attempt-log note and parse it into an `AttemptEvent`,
    /// oldest-first (the Performance recency window relies on the order). These
    /// are ordinary synced Anki notes, so this is exactly what desktop wrote.
    /// Malformed blobs are skipped, matching the desktop read-model seam.
    private static func attemptEvents(_ backend: AnkiBackend) throws -> [AttemptEvent] {
        let noteIds = try backend.searchNotes(matching: AttemptLog.search)
        var events: [AttemptEvent] = []
        events.reserveCapacity(noteIds.count)
        for nid in noteIds {
            let note = try backend.getNote(noteId: nid)
            guard note.fields.count > AttemptLog.eventJsonFieldIndex else { continue }
            if let event = AttemptParser.parse(note.fields[AttemptLog.eventJsonFieldIndex]) {
                events.append(event)
            }
        }
        events.sort { $0.answeredAt < $1.answeredAt }
        return events
    }

    // MARK: Diagnostic (topic placement)

    /// Load the topics to place: every blueprint category in blueprint order,
    /// with its stored placement, reviewed-card count (from Memory), and
    /// objective quick check. Mirrors the desktop pgrep_diagnostic_topics handler
    /// (anki.pgrep.diagnostic.topics): one Memory pass gives the counts, and the
    /// quick-check content is the ported Diagnostic.quickChecks constant (desktop
    /// keeps it as a backend constant, not as cards / notes / tags, so there is no
    /// engine-readable source to read it from).
    func diagnosticTopics() async throws -> [DiagnosticTopic] {
        try await perform { backend in
            let memory = try Engine.memoryResult(backend)
            var nCards: [String: Int] = [:]
            for topic in memory.byTopic { nCards[topic.category] = topic.nCards }
            return Diagnostic.topics(
                stored: try Engine.diagnosticSnapshot(backend),
                nCards: nCards
            )
        }
    }

    /// Whether the Diagnostic has been completed at least once: a non-empty
    /// stored placement snapshot. Mirrors the desktop pgrep_diagnostic_status
    /// handler exactly (a completed run persists a non-empty dict; a never-run
    /// collection has none), so Home / Progress gate identically and a completion
    /// synced down from desktop is honoured here.
    func diagnosticCompleted() async throws -> Bool {
        try await perform { backend in
            !(try Engine.diagnosticSnapshot(backend)).isEmpty
        }
    }

    /// Record a placement pass and persist it: grade each category's quick-check
    /// answer against its key, combine it with the Memory prior, place every
    /// blueprint category, and write the rolled-up snapshot to the collection
    /// config under the SAME key and shape the desktop uses (so it syncs and
    /// pgrep_diagnostic_status matches). Returns the placed topics for the results
    /// screen. A faithful port of anki.pgrep.diagnostic.place.
    @discardableResult
    func placeDiagnostic(answers: [String: Int]) async throws -> [PlacedTopic] {
        try await perform { backend in
            let memory = try Engine.memoryResult(backend)
            let placed = Diagnostic.place(answers: answers, memoryPoints: memory.masteryByCategory)
            let data = try JSONSerialization.data(withJSONObject: Diagnostic.snapshot(from: placed))
            try backend.setConfigJson(key: Diagnostic.configKey, valueJson: data)
            return placed
        }
    }

    /// The stored diagnostic placement snapshot ({category: placement}), or an
    /// empty map when never run or malformed. Mirrors diagnostic._stored_snapshot;
    /// shared by diagnosticTopics and diagnosticCompleted so the read is one seam.
    private static func diagnosticSnapshot(_ backend: AnkiBackend) throws -> [String: String] {
        guard let data = try backend.getConfigJson(key: Diagnostic.configKey), !data.isEmpty,
              let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: String]
        else { return [:] }
        return object
    }

    /// The stored diagnostic placement as typed buckets for the manifold fold,
    /// dropping any unrecognized value (mirrors manifold.py's `_diagnostic_placement`
    /// combined with the desktop `_PLACEMENTS` guard). Empty when the Diagnostic
    /// has never run, so the Home manifold degrades to the Memory-only terrain.
    private static func diagnosticPlacement(_ backend: AnkiBackend) throws -> [String: DiagnosticPlacement] {
        var out: [String: DiagnosticPlacement] = [:]
        for (category, raw) in try diagnosticSnapshot(backend) {
            if let placement = DiagnosticPlacement(rawValue: raw) {
                out[category] = placement
            }
        }
        return out
    }

    // MARK: Exam (Problems, read-only)

    /// Load every `pgrep::Problem` note from the collection as an `ExamProblem`.
    /// Read-only: the stem, choices, correct letter, category, and authored
    /// difficulty are all that Exam mode needs. Empty on a phone whose collection
    /// carries no problems yet (the exam screen then says so honestly). Assembly
    /// and scoring are pure (ExamAssembly / ExamScore) and run off the engine.
    func loadProblems() async throws -> [ExamProblem] {
        try await perform { backend in
            let noteIds = try backend.searchNotes(matching: ProblemNote.search)
            var problems: [ExamProblem] = []
            problems.reserveCapacity(noteIds.count)
            for nid in noteIds {
                let note = try backend.getNote(noteId: nid)
                guard note.fields.count > ProblemNote.correctIndex else { continue }
                let choices = ProblemNote.parseChoices(note.fields[ProblemNote.choicesIndex])
                guard !choices.isEmpty else { continue }
                let correct = note.fields[ProblemNote.correctIndex]
                    .trimmingCharacters(in: .whitespaces).uppercased()
                let difficulty = note.fields.count > ProblemNote.difficultyIndex
                    ? ProblemNote.parseDifficulty(note.fields[ProblemNote.difficultyIndex])
                    : nil
                problems.append(ExamProblem(
                    noteId: note.id,
                    stem: note.fields[ProblemNote.stemIndex],
                    choices: choices,
                    correctLetter: correct,
                    category: Topic.category(forTags: note.tags),
                    topic: Topic.finest(forTags: note.tags),
                    difficulty: difficulty
                ))
            }
            return problems
        }
    }

    // MARK: Attempts (Problems, write path)

    /// Persist a batch of clean, committed attempts as immutable notes, creating
    /// the attempt notetype + deck (schema-identical to desktop) on first use.
    /// This is the write half that closes the loop: after it runs,
    /// `computeScoreboard` reads the SAME notes back through the fold, so a
    /// phone-run exam or ladder moves Performance/Readiness off abstain on-device
    /// exactly like desktop (once a topic crosses its evidence gate). Only clean,
    /// real attempts are ever passed in; nothing here fabricates a number.
    func logAttempts(_ drafts: [AttemptDraft]) async throws {
        guard !drafts.isEmpty else { return }
        try await perform { backend in
            _ = try backend.appendAttempts(drafts)
        }
    }

    /// Load the seeded Problems as `LadderProblem`s for the wrong-answer ladder,
    /// in the desktop rotation order (unseen lead, then last-wrong, then
    /// last-correct; least-recently-touched first), round-robined across
    /// categories (anti-blocking) and capped to a sitting. Unlike Exam (blind),
    /// the ladder carries each item's stored rationales + solution decomposition
    /// so the reveal-and-self-compare rungs are AI-off by construction. The order
    /// reads the attempt log through the same seam Performance uses.
    func loadLadderProblems(limit: Int = LadderSession.problemsPerSession) async throws -> [LadderProblem] {
        try await perform { backend in
            var lastByItem: [Int64: (correct: Bool, answeredAt: Int)] = [:]
            for event in try Engine.attemptEvents(backend) {
                if let nid = event.itemNoteId {
                    lastByItem[nid] = (event.correct, event.answeredAt)
                }
            }

            let noteIds = try backend.searchNotes(matching: ProblemNote.search)
            var problems: [LadderProblem] = []
            problems.reserveCapacity(noteIds.count)
            for nid in noteIds {
                let note = try backend.getNote(noteId: nid)
                guard note.fields.count > ProblemNote.solutionDecompositionIndex else { continue }
                let choices = ProblemNote.parseChoices(note.fields[ProblemNote.choicesIndex])
                guard !choices.isEmpty else { continue }
                let correct = note.fields[ProblemNote.correctIndex]
                    .trimmingCharacters(in: .whitespaces).uppercased()
                let difficulty = note.fields.count > ProblemNote.difficultyIndex
                    ? ProblemNote.parseDifficulty(note.fields[ProblemNote.difficultyIndex])
                    : nil
                problems.append(LadderProblem(
                    noteId: note.id,
                    stem: note.fields[ProblemNote.stemIndex],
                    choices: choices,
                    correctLetter: correct,
                    category: Topic.category(forTags: note.tags),
                    topic: Topic.finest(forTags: note.tags),
                    difficulty: difficulty,
                    rationales: ProblemNote.parseRationales(note.fields[ProblemNote.rationalesIndex]),
                    decomposition: ProblemNote.parseDecomposition(note.fields[ProblemNote.solutionDecompositionIndex])
                ))
            }
            return LadderSession.arrange(problems: problems, lastByItem: lastByItem, limit: limit)
        }
    }

    // MARK: Decomposition tutor (Problems miss, AI off)

    /// Load a Problem note's stored decomposition tutor (its pre-generated
    /// subproblems + numeric variants), a port of the read in
    /// decomposition._load_tutor_data via the note-reading RPC. Reads only. A note
    /// that predates the `decomposition_tutor` field, or whose blob is empty or
    /// malformed, reads as an empty tutor (`hasTutor == false`), so a miss on such
    /// a problem falls back to the honest worked-solution reveal instead of a
    /// gated tutor. Grading and variant selection are pure (DecompositionTutor).
    func loadTutor(noteId: Int64) async throws -> DecompositionTutor {
        try await perform { backend in
            let note = try backend.getNote(noteId: noteId)
            guard note.fields.count > ProblemNote.decompositionTutorIndex else {
                return DecompositionTutor.empty
            }
            return DecompositionTutor.parse(json: note.fields[ProblemNote.decompositionTutorIndex])
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

    // MARK: Settings

    /// Read a collection-config JSON value (raw bytes), or nil when unset. The
    /// pgrep UI preferences (test date, sync url, theme) live in the synced
    /// "pgrepSettings" blob, exactly like desktop's settings module.
    func getConfigJSON(key: String) async throws -> Data? {
        try await perform { backend in try backend.getConfigJson(key: key) }
    }

    /// Write a collection-config JSON value (raw bytes).
    func setConfigJSON(key: String, valueJson: Data) async throws {
        try await perform { backend in try backend.setConfigJson(key: key, valueJson: valueJson) }
    }

    /// The sample deck's target retention (FSRS desiredRetention), best-effort.
    /// Read-only on iOS (adjust on desktop, where it syncs from); falls back to
    /// the default when the deck or value is unavailable. Mirrors the deck the
    /// desktop settings module reads (the seeded "PGRE::Sample" group).
    func targetRetention() async throws -> Double {
        try await perform { backend in
            for name in ["PGRE::Sample", StudySandbox.studyDeckName] {
                let did = try backend.deckId(forName: name)
                guard did != 0 else { continue }
                let update = try backend.deckConfigsForUpdate(deckId: did)
                if let match = update.allConfig.first(where: { $0.config.id == update.currentDeck.configID }) {
                    let value = Double(match.config.config.desiredRetention)
                    if value > 0 { return value }
                }
                let fallback = Double(update.defaults.config.desiredRetention)
                if fallback > 0 { return fallback }
            }
            return 0.9
        }
    }

    /// Reset pgrep progress, conservative and scoped exactly like desktop's
    /// settings.reset_progress: delete the immutable attempt notes (clearing
    /// Performance/Readiness history) and forget the seeded sample cards back to
    /// new (dropping their FSRS memory so Memory starts fresh). Everything else,
    /// including settings and any generated content, is left intact.
    func resetProgress() async throws -> (attemptsDeleted: Int, cardsReset: Int) {
        try await perform { backend in
            self.current = nil  // the queue changes; drop any stale card
            let attemptNoteIds = try backend.searchNotes(matching: AttemptLog.search)
            // Mirrors seed.SEEDED_TAG; duplicated across the boundary on purpose.
            let seededCardIds = try backend.searchCards(matching: "tag:pgrep::seeded")
            if !attemptNoteIds.isEmpty {
                _ = try backend.removeNotes(noteIds: attemptNoteIds)
            }
            if !seededCardIds.isEmpty {
                _ = try backend.scheduleCardsAsNew(cardIds: seededCardIds)
            }
            return (attemptNoteIds.count, seededCardIds.count)
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
