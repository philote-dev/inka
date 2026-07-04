// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// SwiftUI entry point for the pgrep companion. The whole app is a thin UI over
// the shared Rust engine (via AnkiBackend / Engine): a Home glance, a Study
// Cards door, and Settings with two-way sync. It works fully offline and AI off.

import SwiftUI

@main
struct PgrepStudyApp: App {
    var body: some Scene {
        WindowGroup {
            RootView()
        }
    }
}
