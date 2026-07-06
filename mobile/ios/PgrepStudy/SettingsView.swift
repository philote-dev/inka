// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Settings: the AI-off status (this build scores fully without AI) and the sync
// panel. Sync points the shared engine at a self-hosted Anki sync server via a
// custom URL, logs in for an hkey (Keychain), and runs a two-way sync. First-run
// full transfers happen automatically; a real divergence asks for a direction.

import SwiftUI

@MainActor
final class SettingsModel: ObservableObject {
    enum Status: Equatable {
        case idle
        case working(String)
        case ok(String)
        case error(String)
        case needsChoice
    }

    @Published var password = ""
    @Published private(set) var status: Status = .idle

    func logIn(app: AppModel) async {
        let user = app.username.trimmingCharacters(in: .whitespaces)
        guard !user.isEmpty, !password.isEmpty else {
            status = .error("Enter a username and password.")
            return
        }
        status = .working("Logging in…")
        do {
            let hkey = try await app.engine.login(
                username: user, password: password, endpoint: app.normalizedEndpoint
            )
            app.setSyncKey(hkey)
            password = ""
            status = .ok("Signed in.")
        } catch {
            status = .error(Self.describe(error))
        }
    }

    func sync(app: AppModel) async {
        guard let hkey = app.syncKey else {
            status = .error("Log in first.")
            return
        }
        status = .working("Syncing…")
        do {
            switch try await app.engine.sync(hkey: hkey, endpoint: app.normalizedEndpoint) {
            case let .completed(message):
                app.markSynced()
                status = .ok(message ?? "Sync complete.")
            case .conflictNeedsChoice:
                status = .needsChoice
            }
        } catch {
            handle(error: error, app: app)
        }
    }

    func resolve(app: AppModel, upload: Bool) async {
        guard let hkey = app.syncKey else { return }
        status = .working(upload ? "Uploading…" : "Downloading…")
        do {
            try await app.engine.resolveConflict(hkey: hkey, endpoint: app.normalizedEndpoint, upload: upload)
            app.markSynced()
            status = .ok(upload ? "Uploaded to the server." : "Downloaded from the server.")
        } catch {
            handle(error: error, app: app)
        }
    }

    func signOut(app: AppModel) {
        app.setSyncKey(nil)
        status = .idle
    }

    private func handle(error: Error, app: AppModel) {
        if case let AnkiBackendError.backend(err) = error, err.kind == .syncAuthError {
            app.setSyncKey(nil)
            status = .error("Session expired. Please log in again.")
        } else {
            status = .error(Self.describe(error))
        }
    }

    private static func describe(_ error: Error) -> String {
        if case let AnkiBackendError.backend(err) = error, !err.message.isEmpty {
            return err.message
        }
        return String(describing: error)
    }
}

struct SettingsView: View {
    @EnvironmentObject private var app: AppModel
    @StateObject private var model = SettingsModel()

    var body: some View {
        NavigationStack {
            Form {
                aiSection
                syncSection
                statusSection
            }
            .navigationTitle("Settings")
            .scrollContentBackground(.hidden)
            .background(Theme.canvas.ignoresSafeArea())
        }
    }

    private var aiSection: some View {
        Section("Assistant") {
            HStack {
                Text("AI")
                Spacer()
                Text("Off")
                    .foregroundStyle(Theme.muted)
            }
            Text("Scores and study work fully without AI.")
                .font(Theme.Typography.caption)
                .foregroundStyle(Theme.muted)
        }
    }

    private var syncSection: some View {
        Section("Sync") {
            LabeledContent("Server") {
                TextField("http://host:8090/", text: $app.serverURL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .keyboardType(.URL)
                    .multilineTextAlignment(.trailing)
            }
            LabeledContent("Username") {
                TextField("username", text: $app.username)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .multilineTextAlignment(.trailing)
            }
            if app.isLoggedIn {
                Button("Sync now") { Task { await model.sync(app: app) } }
                    .disabled(model.isWorking)
                Button("Sign out", role: .destructive) { model.signOut(app: app) }
            } else {
                SecureField("password", text: $model.password)
                Button("Log in") { Task { await model.logIn(app: app) } }
                    .disabled(model.isWorking)
            }
        }
    }

    @ViewBuilder
    private var statusSection: some View {
        switch model.status {
        case .idle:
            EmptyView()
        case let .working(message):
            Section {
                HStack(spacing: Theme.Space.s) {
                    ProgressView()
                    Text(message).foregroundStyle(Theme.muted)
                }
            }
        case let .ok(message):
            Section {
                Label(message, systemImage: "checkmark.circle")
                    .foregroundStyle(Theme.success)
            }
        case let .error(message):
            Section {
                Label(message, systemImage: "exclamationmark.triangle")
                    .foregroundStyle(Theme.error)
            }
        case .needsChoice:
            Section("Choose a direction") {
                Text("The phone and the server have both changed. Pick which one wins.")
                    .font(Theme.Typography.caption)
                    .foregroundStyle(Theme.muted)
                Button("Upload this device to the server") { Task { await model.resolve(app: app, upload: true) } }
                Button("Download the server to this device", role: .destructive) {
                    Task { await model.resolve(app: app, upload: false) }
                }
            }
        }
    }
}

extension SettingsModel {
    var isWorking: Bool {
        if case .working = status { return true }
        return false
    }
}
