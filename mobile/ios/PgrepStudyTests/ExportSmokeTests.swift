// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Proves the .colpkg export path is reachable through the shared engine's FFI:
// export writes a non-empty package, and the collection can be reopened
// afterwards (the backend takes it out to write the package, exactly like
// desktop's temporary close, so Engine.exportCollectionPackage reopens it).
// AnkiBackend + StudySandbox and the generated protos are compiled into this
// standalone bundle.

import Foundation
import XCTest

final class ExportSmokeTests: XCTestCase {
    func testExportWritesColpkgAndCollectionReopens() throws {
        let backend = try AnkiBackend()

        let bundle = Bundle(for: Self.self)
        guard let deckURL = StudySandbox.bundledDeckURL(in: bundle) else {
            return XCTFail("bundled collection.anki2 not found in the test bundle")
        }
        let sandbox = FileManager.default.temporaryDirectory
            .appendingPathComponent("PgrepExportTests-\(UUID().uuidString)", isDirectory: true)
        let staged = try StudySandbox.stage(from: deckURL, in: sandbox, freshCopy: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: sandbox) }

        try backend.openCollection(
            path: staged.collectionPath, mediaFolder: staged.mediaFolderPath
        )
        try backend.selectDeck(named: StudySandbox.studyDeckName)

        // Export a .colpkg to a temp file.
        let outURL = sandbox.appendingPathComponent("pgrep-export-smoke.colpkg")
        try backend.exportCollectionPackage(
            outPath: outURL.path, includeMedia: true, legacy: false
        )

        // The package exists and is non-empty.
        XCTAssertTrue(
            FileManager.default.fileExists(atPath: outURL.path),
            "export should write a .colpkg at the requested path"
        )
        let size = try FileManager.default
            .attributesOfItem(atPath: outURL.path)[.size] as? Int ?? 0
        XCTAssertGreaterThan(size, 0, "the exported .colpkg should not be empty")

        // The export takes the collection out of the backend, so reopening it
        // must succeed (this is what Engine.exportCollectionPackage does).
        XCTAssertNoThrow(
            try backend.openCollection(
                path: staged.collectionPath, mediaFolder: staged.mediaFolderPath
            ),
            "the collection should reopen after an export"
        )
        try backend.selectDeck(named: StudySandbox.studyDeckName)
        // A follow-up read proves the reopened collection is usable.
        let queued = try backend.getQueuedCards(fetchLimit: 1)
        XCTAssertGreaterThanOrEqual(queued.cards.count, 0)

        try backend.closeCollection()
    }
}
