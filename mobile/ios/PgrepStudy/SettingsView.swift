// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Settings, matching the desktop surface where it makes sense on a phone
// (ts/routes/pgrep/settings/+page.svelte, pylib/anki/pgrep/settings.py):
//
// - Study: target retention (read-only here, adjust on desktop where it syncs
//   from), a test date (persisted in the synced "pgrepSettings" collection blob,
//   exactly like desktop), and the diagnostic re-run (an on-device flow that
//   reopens DiagnosticView).
// - Assistant: AI is off; the app scores and studies fully without it.
// - Sync: the self-hosted server + two-way sync (login, sync, sign out).
// - Appearance: a Light/Dark/System theme, applied app-wide.
// - Data: Export (a .colpkg export runs on desktop; on iPhone, Sync is the
//   backup path) and a scoped, two-step Reset wired through the shared engine.
//
// Controls that cannot be wired safely on iOS in scope (retention writes, colpkg
// export) are shown honestly as read-only or desktop-only rather than faked.
// Everything works with AI off.

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

    // Study settings.
    @Published private(set) var targetRetention: Double?
    @Published var testDateEnabled = false
    @Published var testDate = Date()
    @Published private(set) var loaded = false

    // Reset (two-step, destructive).
    @Published var resetArmed = false
    @Published private(set) var resetting = false
    @Published private(set) var resetMessage: String?
    private var disarmTask: Task<Void, Never>?

    static let settingsKey = "pgrepSettings"

    // MARK: Load

    func load(app: AppModel) async {
        if let retention = try? await app.engine.targetRetention() {
            targetRetention = retention
        }
        if let blob = try? await loadBlob(app: app),
           let stored = blob["test_date"] as? String,
           let date = Self.parseDate(stored) {
            testDate = date
            testDateEnabled = true
        }
        loaded = true
    }

    // MARK: Test date (synced pgrepSettings blob)

    /// Persist the test date into the shared blob, preserving any keys desktop
    /// owns (sync url, theme). A no-op until the initial load has run, so setting
    /// the controls from the loaded value never writes back over it.
    func saveTestDate(app: AppModel) async {
        guard loaded else { return }
        var blob = (try? await loadBlob(app: app)) ?? [:]
        if testDateEnabled {
            blob["test_date"] = Self.formatDate(testDate)
        } else {
            blob.removeValue(forKey: "test_date")
        }
        guard let data = try? JSONSerialization.data(withJSONObject: blob) else { return }
        try? await app.engine.setConfigJSON(key: Self.settingsKey, valueJson: data)
    }

    private func loadBlob(app: AppModel) async throws -> [String: Any] {
        guard let data = try await app.engine.getConfigJSON(key: Self.settingsKey), !data.isEmpty,
              let object = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return [:] }
        return object
    }

    // MARK: Reset

    func onResetTapped(app: AppModel) {
        guard !resetting else { return }
        if resetArmed {
            Task { await confirmReset(app: app) }
        } else {
            armReset()
        }
    }

    private func armReset() {
        resetArmed = true
        resetMessage = nil
        disarmTask?.cancel()
        disarmTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 4_000_000_000)
            self?.resetArmed = false
        }
    }

    private func confirmReset(app: AppModel) async {
        disarmTask?.cancel()
        resetArmed = false
        resetting = true
        resetMessage = "Resetting\u{2026}"
        do {
            let result = try await app.engine.resetProgress()
            resetMessage = "Cleared \(result.attemptsDeleted) attempts and reset \(result.cardsReset) sample cards."
            app.refreshScores()
        } catch {
            resetMessage = "Reset failed. \(Self.describe(error))"
        }
        resetting = false
    }

    var resetLabel: String {
        if resetting { return "Resetting\u{2026}" }
        return resetArmed ? "Confirm reset?" : "Reset"
    }

    var resetHint: String {
        if let resetMessage { return resetMessage }
        if resetArmed { return "This clears your attempts and sample progress. Tap again to confirm." }
        return "Start over. This clears progress, not your cards."
    }

    var retentionText: String {
        guard let targetRetention else { return "\u{2014}" }
        return String(format: "%.2f", targetRetention)
    }

    // MARK: Sync

    func logIn(app: AppModel) async {
        let user = app.username.trimmingCharacters(in: .whitespaces)
        guard !user.isEmpty, !password.isEmpty else {
            status = .error("Enter a username and password.")
            return
        }
        status = .working("Logging in\u{2026}")
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
        status = .working("Syncing\u{2026}")
        do {
            switch try await app.engine.sync(hkey: hkey, endpoint: app.normalizedEndpoint) {
            case let .completed(message):
                app.markSynced()
                // A completion may have synced down from desktop; refresh the gate.
                await app.reloadDiagnosticStatus()
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
        status = .working(upload ? "Uploading\u{2026}" : "Downloading\u{2026}")
        do {
            try await app.engine.resolveConflict(hkey: hkey, endpoint: app.normalizedEndpoint, upload: upload)
            app.markSynced()
            await app.reloadDiagnosticStatus()
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

    // MARK: Date helpers (YYYY-MM-DD, matching desktop)

    static func parseDate(_ value: String) -> Date? { dateFormatter.date(from: value) }
    static func formatDate(_ date: Date) -> String { dateFormatter.string(from: date) }

    private static let dateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter
    }()
}

struct SettingsView: View {
    @EnvironmentObject private var app: AppModel
    @StateObject private var model = SettingsModel()
    @AppStorage(AppTheme.storageKey) private var themeRaw = AppTheme.system.rawValue

    var body: some View {
        NavigationStack {
            Form {
                studySection
                aiSection
                syncSection
                appearanceSection
                dataSection
                statusSection
            }
            .navigationTitle("Settings")
            .scrollContentBackground(.hidden)
            .background(Theme.canvas.ignoresSafeArea())
            .task { await model.load(app: app) }
        }
    }

    private var studySection: some View {
        Section("Study") {
            LabeledContent("Target retention") {
                Text(model.retentionText)
                    .font(Theme.Typography.mono(15))
                    .foregroundStyle(Theme.muted)
            }
            Text("How much you keep before a card comes back. Adjust it on desktop; it syncs here.")
                .font(Theme.Typography.caption)
                .foregroundStyle(Theme.muted)

            Toggle("Set a test date", isOn: $model.testDateEnabled)
            if model.testDateEnabled {
                DatePicker("Test date", selection: $model.testDate, displayedComponents: .date)
            }
            Text("Pacing works back from your test day.")
                .font(Theme.Typography.caption)
                .foregroundStyle(Theme.muted)

            VStack(alignment: .leading, spacing: Theme.Space.xs) {
                HStack {
                    Text("Diagnostic")
                    Spacer()
                    Button("Re-run") { app.isPresentingDiagnostic = true }
                        .buttonStyle(.bordered)
                        .tint(Theme.text)
                }
                Text("Place each topic strong or rusty. Combines a quick check with what your reviews already show.")
                    .font(Theme.Typography.caption)
                    .foregroundStyle(Theme.muted)
            }
        }
        .onChange(of: model.testDateEnabled) { _ in Task { await model.saveTestDate(app: app) } }
        .onChange(of: model.testDate) { _ in Task { await model.saveTestDate(app: app) } }
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

    private var appearanceSection: some View {
        Section("Appearance") {
            Picker("Theme", selection: $themeRaw) {
                ForEach(AppTheme.allCases) { theme in
                    Text(theme.label).tag(theme.rawValue)
                }
            }
            .pickerStyle(.segmented)
            Text("Light and dark are both first class. System follows your device.")
                .font(Theme.Typography.caption)
                .foregroundStyle(Theme.muted)
        }
    }

    private var dataSection: some View {
        Section("Data") {
            comingSoonRow(
                title: "Export",
                detail: "A .colpkg export runs on desktop. On iPhone, Sync backs up your cards, attempts, and history to your server.",
                actionTitle: "Export"
            )

            Button(role: .destructive) {
                model.onResetTapped(app: app)
            } label: {
                HStack {
                    Text(model.resetLabel)
                    Spacer()
                    if model.resetting { ProgressView() }
                }
            }
            .disabled(model.resetting)
            Text(model.resetHint)
                .font(Theme.Typography.caption)
                .foregroundStyle(model.resetArmed ? Theme.error : Theme.muted)
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

    /// A control desktop offers but iOS does not wire in scope: shown honestly as
    /// a disabled action with a note, never a faked result.
    private func comingSoonRow(title: String, detail: String, actionTitle: String) -> some View {
        VStack(alignment: .leading, spacing: Theme.Space.xs) {
            HStack {
                Text(title)
                Spacer()
                Button(actionTitle) {}
                    .buttonStyle(.bordered)
                    .disabled(true)
            }
            Text(detail)
                .font(Theme.Typography.caption)
                .foregroundStyle(Theme.muted)
        }
    }
}

extension SettingsModel {
    var isWorking: Bool {
        if case .working = status { return true }
        return false
    }
}
