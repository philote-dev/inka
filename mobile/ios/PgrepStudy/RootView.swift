// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// The app shell: a bottom tab bar with the companion subset (Home, Study,
// Progress, Settings, per design/ux-foundation.md §4 and §9), gated on opening
// the shared collection once. Library stays desktop-first.

import SwiftUI

enum RootTab: Hashable {
    case home
    case study
    case progress
    case settings
}

struct RootView: View {
    @StateObject private var app = AppModel()
    @State private var tab: RootTab = .home
    // The Settings theme choice, applied app-wide so every tab (and the WebGL
    // manifold, which reads the environment color scheme) switches together.
    @AppStorage(AppTheme.storageKey) private var themeRaw = AppTheme.system.rawValue

    var body: some View {
        content
            .environmentObject(app)
            .preferredColorScheme((AppTheme(rawValue: themeRaw) ?? .system).colorScheme)
            .task { await app.bootstrap() }
    }

    @ViewBuilder
    private var content: some View {
        switch app.phase {
        case .opening:
            gate { ProgressView("Opening pgrep…") }
        case .ready:
            TabView(selection: $tab) {
                HomeView(selectedTab: $tab)
                    .tabItem { Label("Home", systemImage: "circle.hexagongrid") }
                    .tag(RootTab.home)
                StudyView()
                    .tabItem { Label("Study", systemImage: "square.stack") }
                    .tag(RootTab.study)
                ProgressScreen(selectedTab: $tab)
                    .tabItem { Label("Progress", systemImage: "chart.bar") }
                    .tag(RootTab.progress)
                SettingsView()
                    .tabItem { Label("Settings", systemImage: "gearshape") }
                    .tag(RootTab.settings)
            }
            .tint(Theme.text)
        case let .failed(message):
            gate {
                VStack(spacing: Theme.Space.m) {
                    Image(systemName: "exclamationmark.triangle")
                        .font(.system(size: 40))
                        .foregroundStyle(Theme.error)
                    Text("Could not open the collection")
                        .font(Theme.Typography.title)
                        .foregroundStyle(Theme.text)
                    Text(message)
                        .font(Theme.Typography.caption)
                        .foregroundStyle(Theme.muted)
                        .multilineTextAlignment(.center)
                }
                .padding(Theme.Space.xl)
            }
        }
    }

    private func gate<Inner: View>(@ViewBuilder _ inner: () -> Inner) -> some View {
        ZStack {
            Theme.canvas.ignoresSafeArea()
            inner()
        }
    }
}
