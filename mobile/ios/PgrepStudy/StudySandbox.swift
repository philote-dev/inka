// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Stages a writable Anki collection from the read-only bundled sample deck.
// Shared by the SwiftUI app (copies into Documents) and the smoke test (copies
// into a fresh temp dir), so both open the collection exactly the same way.

import Foundation

/// Filesystem paths to hand to `AnkiBackend.openCollection`.
public struct StagedCollection: Sendable {
    public let collectionPath: String
    public let mediaFolderPath: String
}

public enum StudySandbox {
    /// Basename of the bundled deck resource (`collection.anki2`).
    public static let deckResourceName = "collection"
    public static let deckResourceExtension = "anki2"

    /// Top-level deck to study in the bundled sample collection. The cards live
    /// in the "PGRE" deck (and its sub-decks); a freshly opened collection
    /// defaults its current deck to "Default", so clients must select this deck
    /// before the scheduler will queue its cards.
    public static let studyDeckName = "PGRE"

    /// Locate the bundled `collection.anki2` in `bundle`.
    public static func bundledDeckURL(in bundle: Bundle) -> URL? {
        bundle.url(forResource: deckResourceName, withExtension: deckResourceExtension)
    }

    /// Copy the deck at `sourceURL` into `directory` and create a media folder
    /// next to it. When `freshCopy` is true any existing collection at the
    /// destination is replaced (used by tests for a clean slate); otherwise an
    /// existing collection is kept (so the app preserves study progress).
    public static func stage(
        from sourceURL: URL,
        in directory: URL,
        freshCopy: Bool
    ) throws -> StagedCollection {
        let fm = FileManager.default
        try fm.createDirectory(at: directory, withIntermediateDirectories: true)

        let collectionURL = directory.appendingPathComponent("collection.anki2")
        if freshCopy, fm.fileExists(atPath: collectionURL.path) {
            try fm.removeItem(at: collectionURL)
        }
        if !fm.fileExists(atPath: collectionURL.path) {
            try fm.copyItem(at: sourceURL, to: collectionURL)
        }

        let mediaURL = directory.appendingPathComponent("collection.media")
        try fm.createDirectory(at: mediaURL, withIntermediateDirectories: true)

        return StagedCollection(
            collectionPath: collectionURL.path,
            mediaFolderPath: mediaURL.path
        )
    }
}
