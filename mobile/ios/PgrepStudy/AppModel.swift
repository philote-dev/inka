// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// App-level state for the pgrep companion: it owns the one shared Engine (so
// Home, Study, and Settings all drive a single open collection), runs the
// open-on-launch lifecycle, and holds the sync settings (custom server URL and
// username in UserDefaults, the sync key in the Keychain).

import Foundation
import Security
import SwiftUI

@MainActor
final class AppModel: ObservableObject {
    enum Phase: Equatable {
        case opening
        case ready
        case failed(String)
    }

    @Published private(set) var phase: Phase = .opening

    /// The single shared engine. All surfaces route their backend calls here.
    let engine = Engine()

    // MARK: Sync settings

    @Published var serverURL: String {
        didSet { UserDefaults.standard.set(serverURL, forKey: Keys.serverURL) }
    }

    @Published var username: String {
        didSet { UserDefaults.standard.set(username, forKey: Keys.username) }
    }

    @Published private(set) var syncKey: String?

    var isLoggedIn: Bool { syncKey?.isEmpty == false }

    /// Bumped after a sync so surfaces know to reload their data.
    @Published private(set) var dataVersion = 0

    private enum Keys {
        static let serverURL = "pgrep.sync.serverURL"
        static let username = "pgrep.sync.username"
        static let keychainAccount = "syncKey"
    }

    init() {
        let defaults = UserDefaults.standard
        // 8090, not 8080: `just run` uses 8080 for the desktop Qt remote-debug
        // server, so the sync stack uses its own port. The Simulator shares the
        // Mac network, so 127.0.0.1 reaches the desktop's `just sync-server`.
        serverURL = defaults.string(forKey: Keys.serverURL) ?? "http://127.0.0.1:8090/"
        username = defaults.string(forKey: Keys.username) ?? "pgrep"
        syncKey = Keychain.get(account: Keys.keychainAccount)
    }

    /// Stage the bundled deck into Documents and open it once.
    func bootstrap() async {
        guard phase == .opening else { return }
        do {
            guard let deckURL = StudySandbox.bundledDeckURL(in: .main) else {
                phase = .failed("Bundled collection.anki2 not found in app bundle")
                return
            }
            let documents = try FileManager.default.url(
                for: .documentDirectory, in: .userDomainMask, appropriateFor: nil, create: true
            )
            let directory = documents.appendingPathComponent("PgrepStudy", isDirectory: true)
            let staged = try StudySandbox.stage(from: deckURL, in: directory, freshCopy: false)
            try await engine.open(collectionPath: staged.collectionPath, mediaFolder: staged.mediaFolderPath)
            phase = .ready
        } catch {
            phase = .failed(String(describing: error))
        }
    }

    // MARK: Sync actions

    func setSyncKey(_ key: String?) {
        syncKey = key
        Keychain.set(key, account: Keys.keychainAccount)
    }

    func markSynced() {
        dataVersion &+= 1
    }

    /// The endpoint with a guaranteed trailing slash (the engine joins "./").
    var normalizedEndpoint: String {
        serverURL.hasSuffix("/") ? serverURL : serverURL + "/"
    }
}

/// Minimal Keychain wrapper for a single string secret (the sync key). The sync
/// key is a credential, so it never goes in UserDefaults, notes, or sync.
enum Keychain {
    private static let service = "net.ankiweb.pgrep.sync"

    static func get(account: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data,
              let value = String(data: data, encoding: .utf8)
        else { return nil }
        return value
    }

    static func set(_ value: String?, account: String) {
        let base: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(base as CFDictionary)
        guard let value, let data = value.data(using: .utf8) else { return }
        var add = base
        add[kSecValueData as String] = data
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
        SecItemAdd(add as CFDictionary, nil)
    }
}
