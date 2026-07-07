// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Target-retention bounds and clamping, ported from pylib/anki/pgrep/settings.py
// (MIN_RETENTION, MAX_RETENTION, DEFAULT_RETENTION, clamp_retention). Kept as a
// tiny pure helper so the Settings slider, the engine write, and the tests all
// share one source of truth for the supported range.

import Foundation

enum Retention {
    /// The supported desired-retention range and default, matching settings.py.
    static let min = 0.7
    static let max = 0.97
    static let `default` = 0.9

    /// Coerce a value into the supported range, falling back to the default for a
    /// non-finite input (mirrors settings.clamp_retention).
    static func clamp(_ value: Double) -> Double {
        guard value.isFinite else { return `default` }
        return Swift.max(min, Swift.min(max, value))
    }
}
