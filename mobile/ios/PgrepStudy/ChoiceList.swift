// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Pure, testable core for the shared multiple-choice list, ported from
// ts/lib/components/ChoiceList.svelte. This file holds the option model, the row
// states, and the two pieces of logic worth pinning (letter labeling and the
// pre/post-commit state resolution); ChoiceListView.swift draws them. Splitting
// logic from the SwiftUI view follows the codebase's ExamScore/ExamView and
// StudySession/StudySessionView pattern and lets the standalone (host-less) test
// bundle exercise the logic without a running app.

import Foundation

/// One selectable option: a short letter key (A, B, ...) and the choice body as
/// HTML with LaTeX math (rendered by MathText). Mirrors the `{ key, html }` shape
/// the Svelte ChoiceList consumes.
struct ChoiceOption: Identifiable, Equatable {
    let key: String
    let html: String
    var id: String { key }

    init(key: String, html: String) {
        self.key = key
        self.html = html
    }
}

/// The visual state of one choice row, resolved from the live selection and the
/// post-commit reveal. A direct port of ChoiceList.svelte's `rowState`.
///
/// pgrep honesty rule (ux-foundation.md, and the Svelte component's own header):
/// a wrong committed pick is NEVER shown in red. It reads neutrally (dimmed, with
/// a quiet "Not correct" marker) while the correct choice is affirmed in the
/// success tone. The Svelte source carries a red `.state-wrong` block flagged as
/// an experiment "under review, diverges from the honesty rule"; we deliberately
/// do not port that (see ChoiceListView).
enum ChoiceRowState: Equatable {
    /// Pre-commit, not the live selection.
    case normal
    /// Pre-commit, the live selection (calm blue outline).
    case selected
    /// Post-commit, the correct choice (affirmed in success).
    case correct
    /// Post-commit, the learner's pick when it was wrong (neutral, never red).
    case wrong
    /// Post-commit, an unpicked choice (dimmed).
    case locked
}

/// Namespaced logic for the choice list (no SwiftUI, so it is unit-testable).
enum ChoiceList {
    /// Resolve a row's state. Ported verbatim from ChoiceList.svelte:
    ///   pre-commit -> `selected` if it is the pick, else `normal`;
    ///   committed  -> `correct` if it is the answer, else `wrong` if it is the
    ///                 pick, else `locked`.
    /// A correct pick resolves to `correct` (the answer reveal wins over the
    /// pick), so a right answer is affirmed rather than merely marked as chosen.
    static func rowState(
        key: String,
        selected: String?,
        committed: Bool,
        correctKey: String?
    ) -> ChoiceRowState {
        guard committed else {
            return key == selected ? .selected : .normal
        }
        if let correctKey, key == correctKey {
            return .correct
        }
        if let selected, key == selected {
            return .wrong
        }
        return .locked
    }

    /// The letter label for a 0-based choice index: A, B, ... Z, AA, AB, ...
    /// (bijective base-26). Problems use A..E, but this stays defined for any
    /// count so callers never fall back to a placeholder.
    static func letter(for index: Int) -> String {
        guard index >= 0 else { return "?" }
        var value = index
        var label = ""
        repeat {
            let remainder = value % 26
            label = String(UnicodeScalar(UInt8(65 + remainder))) + label
            value = value / 26 - 1
        } while value >= 0
        return label
    }

    /// Build letter-labeled options (A, B, ...) from ordered HTML bodies, the
    /// common case where the caller has a plain array of choice strings.
    static func lettered(_ bodies: [String]) -> [ChoiceOption] {
        bodies.enumerated().map { ChoiceOption(key: letter(for: $0.offset), html: $0.element) }
    }
}
