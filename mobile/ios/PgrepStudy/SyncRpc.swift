// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Sync RPCs for the iOS companion. These reuse Anki's own sync engine over the
// shared C ABI: nothing under rslib/src/sync is touched. The (service, method)
// ids are BackendSyncService, verified against out/pylib/anki/_backend_generated.py
// (service 1). Kept in its own file so the sync surface never edits the core
// AnkiBackend bridge.

import Foundation
import SwiftProtobuf

// BackendSyncService = service 1 (order matches proto/anki/sync.proto).
extension RpcId {
    public static let syncLogin = RpcId(1, 3)
    public static let syncCollection = RpcId(1, 5)
    public static let fullUploadOrDownload = RpcId(1, 6)
}

extension AnkiBackend {
    /// Exchange username/password for an hkey against the given self-hosted
    /// endpoint (for example "http://127.0.0.1:8080/"). The endpoint is echoed
    /// back on the returned auth by the engine.
    public func syncLogin(username: String, password: String, endpoint: String) throws -> Anki_Sync_SyncAuth {
        var req = Anki_Sync_SyncLoginRequest()
        req.username = username
        req.password = password
        req.endpoint = endpoint
        return try call(.syncLogin, req)
    }

    /// Run a normal (incremental) sync. Reviews and Attempt notes union by id;
    /// same-card scheduling state resolves by newer mtime. The response's
    /// `required` says whether a full up/download is needed instead.
    public func syncCollection(auth: Anki_Sync_SyncAuth, syncMedia: Bool = false) throws -> Anki_Sync_SyncCollectionResponse {
        var req = Anki_Sync_SyncCollectionRequest()
        req.auth = auth
        req.syncMedia = syncMedia
        return try call(.syncCollection, req)
    }

    /// Full one-way transfer (used on first sync or a forced full sync). Media
    /// is skipped when `server_usn` is omitted.
    public func fullUploadOrDownload(auth: Anki_Sync_SyncAuth, upload: Bool) throws {
        var req = Anki_Sync_FullUploadOrDownloadRequest()
        req.auth = auth
        req.upload = upload
        let _: Anki_Generic_Empty = try call(.fullUploadOrDownload, req)
    }
}
