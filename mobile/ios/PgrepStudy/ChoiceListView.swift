// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// The shared multiple-choice list, a native port of
// ts/lib/components/ChoiceList.svelte. It is the MCQ primitive that study, exam,
// the decomposition tutor, the diagnostic, and calibration all draw. Pre-commit
// the rows are selectable and one carries a calm blue outline; after commit the
// group locks and reveals: the correct choice is affirmed in the success tone and
// the learner's pick, if wrong, reads neutrally with a quiet "Not correct" marker.
//
// pgrep honesty rule: a wrong answer is NEVER red. The Svelte source ships a red
// `.state-wrong` block flagged as an experiment "under review, diverges from the
// calm-blue honesty rule", so we follow the component's documented intent (its
// header: "a wrong commit dims and wears a not-correct tag. Never red.") and use
// neutral tokens instead. The correct choice is the only affirmed one.
//
// Presentation only: no engine calls. The caller owns the selection (a binding),
// says whether the group is committed, and supplies the revealed correct key.

import SwiftUI

struct ChoiceListView: View {
    let choices: [ChoiceOption]
    /// The learner's current pick (a choice key), or nil when nothing is chosen.
    @Binding var selected: String?
    /// Once true the group locks and reveals the answer.
    var committed: Bool = false
    /// The correct choice key, revealed after commit (nil keeps the reveal off).
    var correctKey: String? = nil
    /// Fired when the learner picks a choice (pre-commit only), alongside the
    /// binding write, for callers that want to react (log, advance, enable commit).
    var onSelect: ((String) -> Void)? = nil

    /// The Svelte list uses a 10pt gap between rows.
    private let rowGap: CGFloat = 10

    var body: some View {
        VStack(spacing: rowGap) {
            ForEach(choices) { choice in
                row(choice)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Answer choices")
    }

    private func row(_ choice: ChoiceOption) -> some View {
        let state = ChoiceList.rowState(
            key: choice.key,
            selected: selected,
            committed: committed,
            correctKey: correctKey
        )
        let stroke = border(for: state)
        return Button {
            guard !committed else { return }
            selected = choice.key
            onSelect?(choice.key)
        } label: {
            HStack(alignment: .center, spacing: Theme.Space.m) {
                keyBadge(choice.key, state: state)
                MathText(html: choice.html, fontSize: 16)
                    .frame(maxWidth: .infinity, alignment: .leading)
                if state == .wrong {
                    notCorrectTag
                }
            }
            .padding(.vertical, 14)
            .padding(.horizontal, 18)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: Theme.Radius.row, style: .continuous)
                    .fill(background(for: state))
            )
            .overlay(
                RoundedRectangle(cornerRadius: Theme.Radius.row, style: .continuous)
                    .strokeBorder(stroke.color, lineWidth: stroke.width)
            )
            .opacity(opacity(for: state))
            .contentShape(RoundedRectangle(cornerRadius: Theme.Radius.row, style: .continuous))
        }
        .buttonStyle(.plain)
        .disabled(committed)
        .animation(Theme.Motion.spring, value: state)
        .accessibilityLabel(Text(choice.key))
        .accessibilityValue(Text(accessibilityValue(for: state)))
        .accessibilityAddTraits(state == .selected ? .isSelected : [])
    }

    // MARK: Letter badge

    private func keyBadge(_ key: String, state: ChoiceRowState) -> some View {
        Text(key)
            .font(Theme.Typography.mono(12, weight: state == .correct ? .semibold : .regular))
            .foregroundStyle(badgeText(for: state))
            .frame(width: 26, height: 26)
            .background(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(state == .correct ? Theme.success : Color.clear)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .strokeBorder(badgeBorder(for: state), lineWidth: 1)
            )
    }

    private var notCorrectTag: some View {
        Text("Not correct")
            .font(Theme.Typography.caption)
            .foregroundStyle(Theme.muted)
            .padding(.vertical, 3)
            .padding(.horizontal, 10)
            .overlay(
                RoundedRectangle(cornerRadius: Theme.Radius.pill, style: .continuous)
                    .strokeBorder(Theme.muted.opacity(0.6), lineWidth: 1)
            )
            .fixedSize()
    }

    // MARK: State to tokens
    //
    // Selection is Performance blue (the shared component's live-selection
    // affordance); the reveal affirms only the correct choice in success green.
    // A wrong pick stays neutral (never a score hue, never red).

    private func background(for state: ChoiceRowState) -> Color {
        switch state {
        case .selected: return Theme.performance.opacity(0.12)
        case .correct: return Theme.success.opacity(0.22)
        case .normal, .wrong, .locked: return .clear
        }
    }

    private func border(for state: ChoiceRowState) -> (color: Color, width: CGFloat) {
        switch state {
        case .normal: return (Theme.border, 1)
        case .selected: return (Theme.performance, 2)
        case .correct: return (Theme.success, 2)
        case .wrong: return (Theme.muted, 1.5)
        case .locked: return (Theme.border, 1)
        }
    }

    private func opacity(for state: ChoiceRowState) -> Double {
        switch state {
        case .locked: return 0.5
        case .wrong: return 0.72
        default: return 1
        }
    }

    private func badgeText(for state: ChoiceRowState) -> Color {
        switch state {
        case .normal, .locked, .wrong: return Theme.muted
        case .selected: return Theme.performanceText
        // Dark-on-green in light mode (matches the Svelte `--action-bg` text).
        case .correct: return Theme.actionBg
        }
    }

    private func badgeBorder(for state: ChoiceRowState) -> Color {
        switch state {
        case .selected: return Theme.performance
        case .correct: return Theme.success
        case .wrong: return Theme.muted
        case .normal, .locked: return Theme.border
        }
    }

    private func accessibilityValue(for state: ChoiceRowState) -> String {
        switch state {
        case .normal, .locked: return "not selected"
        case .selected: return "selected"
        case .correct: return "correct answer"
        case .wrong: return "your answer, not correct"
        }
    }
}

// MARK: - Preview

#if DEBUG
private let choiceListPreviewData = ChoiceList.lettered([
    "A traveling wave whose speed grows with the tension",
    "A standing wave with a node at each fixed end",
    "Speed follows \\(v = f\\lambda\\) in every medium",
    "A damped oscillation that decays within one period",
    "None of the above",
])

/// Pre-commit, correct-after-commit, and wrong-after-commit in one scroll, so all
/// three states (and the honesty rule for the wrong pick) are reviewable at once.
private struct ChoiceListPreviewGallery: View {
    @State private var pick: String? = "B"

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Space.l) {
                label("Pre-commit, selectable")
                ChoiceListView(choices: choiceListPreviewData, selected: $pick)

                label("Committed, correct pick affirmed")
                ChoiceListView(
                    choices: choiceListPreviewData,
                    selected: .constant(String?("B")),
                    committed: true,
                    correctKey: "B"
                )

                label("Committed, wrong pick (neutral, never red)")
                ChoiceListView(
                    choices: choiceListPreviewData,
                    selected: .constant(String?("D")),
                    committed: true,
                    correctKey: "B"
                )
            }
            .padding(Theme.Space.l)
        }
        .background(Theme.canvas)
    }

    private func label(_ text: String) -> some View {
        Text(text)
            .font(Theme.Typography.caption)
            .foregroundStyle(Theme.muted)
    }
}

#Preview("ChoiceList light") {
    ChoiceListPreviewGallery().preferredColorScheme(.light)
}

#Preview("ChoiceList dark") {
    ChoiceListPreviewGallery().preferredColorScheme(.dark)
}
#endif
