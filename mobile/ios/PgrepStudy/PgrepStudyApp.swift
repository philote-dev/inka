// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// SwiftUI entry point for the PGRE study app. The whole app is a thin UI over
// AnkiBackend, which drives the same shared Rust engine that desktop uses.

import SwiftUI

@main
struct PgrepStudyApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
    
    init() {
        // Require full screen mode if limiting orientations
        // This should be set in Info.plist as well
    }
}
