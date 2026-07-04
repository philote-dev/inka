// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Proves the iOS sync path end to end over the shared C ABI: review a card, then
// log in and sync to a self-hosted anki-sync-server using the exact
// BackendSyncService RPCs the app uses. It is opt-in: it runs only when a config
// file describing a reachable server is present, so `just ios-smoke` stays green
// with no server. Drive it with tools/ios-sync-proof.sh, which starts a server,
// writes the config, runs this test, and confirms the upload from a desktop
// engine.

import Foundation
import XCTest

// AnkiBackend, SyncRpc, StudySandbox, and the generated protos are compiled into
// this standalone test bundle, so no module import is needed.

final class SyncSmokeTests: XCTestCase {
    private struct Config: Decodable {
        let url: String
        let user: String
        let pass: String
    }

    /// Where tools/ios-sync-proof.sh drops the server details. The iOS Simulator
    /// can read host paths, so a plain /tmp file is the simplest hand-off.
    private static let configPath = "/tmp/pgrep-sync-test.json"

    func testSyncToSelfHostedServer() throws {
        guard let data = FileManager.default.contents(atPath: Self.configPath) else {
            throw XCTSkip("no \(Self.configPath); run tools/ios-sync-proof.sh for the sync proof")
        }
        let cfg = try JSONDecoder().decode(Config.self, from: data)

        let backend = try AnkiBackend()
        let bundle = Bundle(for: Self.self)
        guard let deckURL = StudySandbox.bundledDeckURL(in: bundle) else {
            return XCTFail("bundled collection.anki2 not found in the test bundle")
        }
        let sandbox = FileManager.default.temporaryDirectory
            .appendingPathComponent("PgrepSyncTests-\(UUID().uuidString)", isDirectory: true)
        let staged = try StudySandbox.stage(from: deckURL, in: sandbox, freshCopy: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: sandbox) }

        try backend.openCollection(path: staged.collectionPath, mediaFolder: staged.mediaFolderPath)
        try backend.selectDeck(named: StudySandbox.studyDeckName)

        // Review one card so the uploaded collection carries a fresh revlog row,
        // which the desktop-side check then confirms it received.
        let queue = try backend.getQueuedCards(fetchLimit: 1)
        let card = try XCTUnwrap(queue.cards.first)
        var answer = Anki_Scheduler_CardAnswer()
        answer.cardID = card.card.id
        answer.currentState = card.states.current
        answer.newState = card.states.good
        answer.rating = .good
        answer.answeredAtMillis = Int64(Date().timeIntervalSince1970 * 1000)
        answer.millisecondsTaken = 1000
        try backend.answerCard(answer)

        // Log in for an hkey and sync to the self-hosted server. If the server
        // is unreachable (for example a stale config left by a killed proof
        // run), skip rather than fail so `just ios-smoke` stays green.
        let auth: Anki_Sync_SyncAuth
        do {
            auth = try backend.syncLogin(username: cfg.user, password: cfg.pass, endpoint: cfg.url)
        } catch {
            throw XCTSkip("sync server at \(cfg.url) not reachable (stale config?): \(error)")
        }
        XCTAssertFalse(auth.hkey.isEmpty, "login should return an hkey")

        let first = try backend.syncCollection(auth: auth)
        switch first.required {
        case .fullUpload, .fullSync:
            try backend.fullUploadOrDownload(auth: auth, upload: true)
        case .fullDownload:
            try backend.fullUploadOrDownload(auth: auth, upload: false)
        case .noChanges, .normalSync, .UNRECOGNIZED:
            break
        }

        // A second sync settles cleanly (the phone and server agree).
        let second = try backend.syncCollection(auth: auth)
        XCTAssertTrue(
            second.required == .noChanges || second.required == .normalSync,
            "expected a clean second sync, got \(second.required)"
        )

        try backend.closeCollection()
    }
}
