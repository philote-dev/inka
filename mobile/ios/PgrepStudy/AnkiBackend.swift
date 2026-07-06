// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Swift wrapper around Anki's shared engine C ABI (see rslib/ffi + the
// CAnkiFfi module map). Every call crosses the boundary as protobuf bytes via
// the universal run_service_method(service, method, bytes) RPC, exactly like
// pylib/rsbridge does for desktop. This is the seam that lets the iOS app drive
// the *same* Rust engine that desktop uses.

import CAnkiFfi
import Foundation
import SwiftProtobuf

/// A verified (service, method) pair for `Backend::run_service_method`. The ids
/// come from the generated backend service table (see proto/anki/*.proto); they
/// must stay in sync with the Rust side.
public struct RpcId: Sendable {
    public let service: UInt32
    public let method: UInt32

    public init(_ service: UInt32, _ method: UInt32) {
        self.service = service
        self.method = method
    }

    // CollectionService (service 3)
    public static let openCollection = RpcId(3, 0)
    public static let closeCollection = RpcId(3, 1)
    public static let pgrepSeamCheck = RpcId(3, 16)
    // DecksService (service 7)
    public static let getDeckIdByName = RpcId(7, 7)
    public static let setCurrentDeck = RpcId(7, 22)
    // SchedulerService (service 13)
    public static let getQueuedCards = RpcId(13, 3)
    public static let answerCard = RpcId(13, 4)
    // SearchService (service 29)
    public static let searchCards = RpcId(29, 1)
    public static let searchNotes = RpcId(29, 2)
    // StatsService (service 43)
    public static let cardStats = RpcId(43, 0)
    // NotesService (service 25)
    public static let getNote = RpcId(25, 6)
}

/// Errors surfaced by the engine bridge.
public enum AnkiBackendError: Error, CustomStringConvertible {
    /// `anki_ffi_open` returned NULL (bad init bytes or a caught panic).
    case openFailed
    /// `anki_ffi_run` returned NULL: a hard failure (NULL handle or caught panic).
    case hardFailure(service: UInt32, method: UInt32)
    /// The backend returned an encoded `anki.backend.BackendError`.
    case backend(Anki_Backend_BackendError)
    /// The backend signalled an error but the payload wasn't a BackendError.
    case backendUndecodable(Data)
    /// A deck lookup by name returned no match.
    case deckNotFound(String)

    public var description: String {
        switch self {
        case .openFailed:
            return "anki_ffi_open returned NULL (failed to open backend)"
        case let .hardFailure(service, method):
            return "anki_ffi_run hard failure for (service: \(service), method: \(method))"
        case let .backend(err):
            return "backend error (\(err.kind)): \(err.message)"
        case .backendUndecodable:
            return "backend error with an undecodable payload"
        case let .deckNotFound(name):
            return "no deck named \"\(name)\" was found in the collection"
        }
    }
}

/// Owns an `AnkiBackend *` handle and drives it over the C ABI. Not thread-safe;
/// use one instance per serial context (the app uses it from the main actor,
/// the tests from the test thread).
public final class AnkiBackend {
    private let handle: OpaquePointer

    /// Open a backend. `initData` is an encoded `anki.backend.BackendInit`;
    /// empty bytes (the default) select engine defaults.
    public init(initData: Data = Data()) throws {
        let opened: OpaquePointer? = initData.withUnsafeBytes { raw in
            anki_ffi_open(raw.bindMemory(to: UInt8.self).baseAddress, raw.count)
        }
        guard let opened else { throw AnkiBackendError.openFailed }
        handle = opened
    }

    deinit {
        anki_ffi_close(handle)
    }

    // MARK: - Low-level RPC

    /// Run a raw RPC. Throws only on a *hard* failure (NULL return); a backend
    /// error is reported via the returned `isErr` flag (the bytes are then an
    /// encoded `anki.backend.BackendError`). The FFI buffer is freed internally.
    @discardableResult
    public func run(service: UInt32, method: UInt32, input: Data) throws -> (data: Data, isErr: Bool) {
        var outLen = 0
        var isErr = false
        let ptr: UnsafeMutablePointer<UInt8>? = input.withUnsafeBytes { raw in
            anki_ffi_run(
                handle,
                service,
                method,
                raw.bindMemory(to: UInt8.self).baseAddress,
                raw.count,
                &outLen,
                &isErr
            )
        }
        guard let ptr else {
            throw AnkiBackendError.hardFailure(service: service, method: method)
        }
        let data = outLen > 0 ? Data(bytes: ptr, count: outLen) : Data()
        anki_ffi_free(ptr, outLen)
        return (data, isErr)
    }

    /// Encode `request`, run `id`, and decode the response as `Response`
    /// (inferred from the call site). Throws on a hard failure *and* on a
    /// backend error.
    public func call<Request: SwiftProtobuf.Message, Response: SwiftProtobuf.Message>(
        _ id: RpcId,
        _ request: Request
    ) throws -> Response {
        let input = try request.serializedData()
        let (data, isErr) = try run(service: id.service, method: id.method, input: input)
        if isErr {
            if let err = try? Anki_Backend_BackendError(serializedBytes: data) {
                throw AnkiBackendError.backend(err)
            }
            throw AnkiBackendError.backendUndecodable(data)
        }
        return try Response(serializedBytes: data)
    }

    // MARK: - Typed helpers

    /// Open a collection at `path`, using `mediaFolder` for media (created by the
    /// caller). Passing an empty `mediaDb` lets the engine derive it.
    public func openCollection(path: String, mediaFolder: String, mediaDb: String = "") throws {
        var req = Anki_Collection_OpenCollectionRequest()
        req.collectionPath = path
        req.mediaFolderPath = mediaFolder
        req.mediaDbPath = mediaDb
        let _: Anki_Generic_Empty = try call(.openCollection, req)
    }

    public func closeCollection(downgradeToSchema11: Bool = false) throws {
        var req = Anki_Collection_CloseCollectionRequest()
        req.downgradeToSchema11 = downgradeToSchema11
        let _: Anki_Generic_Empty = try call(.closeCollection, req)
    }

    /// Resolve a deck id from its human-readable name (use "Parent::Child" for
    /// sub-decks). Returns 0 when no deck matches.
    public func deckId(forName name: String) throws -> Int64 {
        var req = Anki_Generic_String()
        req.val = name
        let res: Anki_Decks_DeckId = try call(.getDeckIdByName, req)
        return res.did
    }

    /// Make `deckId` the current deck. The scheduler builds its queue from the
    /// current deck's subtree, so this must be set before `getQueuedCards` for a
    /// specific deck's cards to appear (mirrors selecting a deck in desktop).
    @discardableResult
    public func setCurrentDeck(deckId: Int64) throws -> Anki_Collection_OpChanges {
        var req = Anki_Decks_DeckId()
        req.did = deckId
        return try call(.setCurrentDeck, req)
    }

    /// Select the deck named `name` (and its sub-decks) for study. Throws
    /// `AnkiBackendError.deckNotFound` if the collection has no such deck.
    public func selectDeck(named name: String) throws {
        let did = try deckId(forName: name)
        guard did != 0 else { throw AnkiBackendError.deckNotFound(name) }
        try setCurrentDeck(deckId: did)
    }

    /// Round-trips the pgrep seam marker through Rust; expected to return
    /// "pgrep seam OK (Rust)".
    public func pgrepSeamCheck() throws -> String {
        let res: Anki_Generic_String = try call(.pgrepSeamCheck, Anki_Generic_Empty())
        return res.val
    }

    public func getQueuedCards(
        fetchLimit: UInt32 = 10,
        intradayLearningOnly: Bool = false
    ) throws -> Anki_Scheduler_QueuedCards {
        var req = Anki_Scheduler_GetQueuedCardsRequest()
        req.fetchLimit = fetchLimit
        req.intradayLearningOnly = intradayLearningOnly
        return try call(.getQueuedCards, req)
    }

    public func getNote(noteId: Int64) throws -> Anki_Notes_Note {
        var req = Anki_Notes_NoteId()
        req.nid = noteId
        return try call(.getNote, req)
    }

    @discardableResult
    public func answerCard(_ answer: Anki_Scheduler_CardAnswer) throws -> Anki_Collection_OpChanges {
        return try call(.answerCard, answer)
    }

    /// Find card ids matching an Anki search string (for example "tag:topic::*").
    /// Order is left at the engine default; the Memory fold does not depend on it.
    public func searchCards(matching search: String) throws -> [Int64] {
        var req = Anki_Search_SearchRequest()
        req.search = search
        let res: Anki_Search_SearchResponse = try call(.searchCards, req)
        return res.ids
    }

    /// Find note ids matching an Anki search string (for example
    /// "tag:pgrep::attempt"). Used by the score fold to read the immutable
    /// attempt-log notes desktop wrote; order is left at the engine default.
    public func searchNotes(matching search: String) throws -> [Int64] {
        var req = Anki_Search_SearchRequest()
        req.search = search
        let res: Anki_Search_SearchResponse = try call(.searchNotes, req)
        return res.ids
    }

    /// Per-card stats, including the engine's own FSRS retrievability
    /// (`fsrsRetrievability`, unset for cards with no memory state). Using the
    /// engine value keeps mobile Memory identical to desktop by construction.
    public func cardStats(cardId: Int64) throws -> Anki_Stats_CardStatsResponse {
        var req = Anki_Cards_CardId()
        req.cid = cardId
        return try call(.cardStats, req)
    }
}
