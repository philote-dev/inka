// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// One gated step of the decomposition tutor, a SwiftUI port of
// ts/lib/components/SubproblemCard.svelte. The learner answers a mini MCQ
// (unlimited retries, a wrong pick shows only that distractor's rationale, never
// the key), then reveals the model rationale and advances to the next step.
//
// AI off: the desktop card carries a second gate, a graded free-text "explain
// why" that shows only with AI on. This app is AI off by construction, so that
// gate is absent here and the MCQ alone satisfies the step. There is no skip
// control: the learner advances only once the step is satisfied.
//
// pgrep honesty rule: a wrong pick is NEVER red. The Svelte source styles the
// wrong-pick rationale in pastel red, flagged in its own comment as an experiment
// "under review, diverges from the calm-blue honesty rule". We follow the
// documented intent instead: the rationale reads as a calm, neutral note, and the
// shared ChoiceListView already refuses red for a wrong committed choice.
//
// Presentational: the parent (StudySessionModel) owns the flow, the backend
// grading, and the step transitions. This renders a single step from its inputs
// and reports the two actions (Check, Continue) through callbacks.

import SwiftUI

/// The phase of one subproblem step. AI off, so there are only two: the MCQ is
/// open, or it is satisfied and the learner may continue (the desktop's third
/// "explain" phase exists only with AI on).
enum SubproblemPhase: Equatable {
    case mcq
    case done
}

struct SubproblemCardView: View {
    let step: TutorStep
    /// 1-based number of this step, for the "Step k of n" chrome.
    let stepNumber: Int
    let total: Int
    /// The learner's MCQ pick, or nil when nothing is chosen (bound to the model).
    @Binding var selected: String?
    let phase: SubproblemPhase
    /// The subproblem's correct key, revealed only once the step is satisfied.
    let correctKey: String?
    /// Shown after a wrong pick (calm, never red). Empty otherwise.
    let rationaleHtml: String
    /// The model "why", revealed once the step is satisfied. Empty when absent.
    let explainWhyHtml: String
    let isLast: Bool
    var onCheck: () -> Void
    var onContinue: () -> Void

    private var locked: Bool { phase != .mcq }

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Space.m) {
            header

            if !step.prompt.isEmpty {
                Text(step.prompt)
                    .font(Theme.Typography.caption)
                    .textCase(.uppercase)
                    .foregroundStyle(Theme.muted)
            }

            MathText(html: step.stemHtml, fontSize: 16)
                .frame(maxWidth: .infinity, alignment: .leading)

            ChoiceListView(
                choices: ChoiceList.lettered(step.choices),
                selected: $selected,
                committed: locked,
                correctKey: locked ? correctKey : nil
            )

            if phase == .mcq {
                mcqSection
            } else {
                doneSection
            }
        }
        .padding(Theme.Space.l)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.surface)
        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous)
                .stroke(Theme.border, lineWidth: 1)
        )
    }

    // MARK: Header (step count + progress dots)

    private var header: some View {
        HStack {
            Text("Step \(stepNumber) of \(total)")
                .font(Theme.Typography.caption)
                .textCase(.uppercase)
                .foregroundStyle(Theme.muted)
            Spacer()
            HStack(spacing: 5) {
                ForEach(0 ..< max(total, 1), id: \.self) { i in
                    Circle()
                        .fill(i < stepNumber ? Theme.performance : Color.clear)
                        .overlay(Circle().strokeBorder(i < stepNumber ? Theme.performance : Theme.muted, lineWidth: 1))
                        .frame(width: 7, height: 7)
                }
            }
            .accessibilityHidden(true)
        }
    }

    // MARK: MCQ gate (open)

    @ViewBuilder
    private var mcqSection: some View {
        if !rationaleHtml.isEmpty {
            calmNote(rationaleHtml)
            Text("Try again.")
                .font(Theme.Typography.caption)
                .foregroundStyle(Theme.muted)
        }
        Button {
            onCheck()
        } label: {
            Text("Check")
                .font(Theme.Typography.emphasis)
                .frame(maxWidth: .infinity)
                .padding(.vertical, Theme.Space.m)
                .background((selected ?? "").isEmpty ? Theme.elevated : Theme.actionBg)
                .foregroundStyle((selected ?? "").isEmpty ? Theme.muted : Theme.actionFg)
                .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))
        }
        .disabled((selected ?? "").isEmpty)
    }

    // MARK: Satisfied (the MCQ is right; reveal the model rationale)

    @ViewBuilder
    private var doneSection: some View {
        Text("That's right.")
            .font(Theme.Typography.emphasis)
            .foregroundStyle(Theme.success)

        if !explainWhyHtml.isEmpty {
            Divider().background(Theme.border)
            VStack(alignment: .leading, spacing: Theme.Space.xs) {
                Text("Why")
                    .font(Theme.Typography.caption)
                    .textCase(.uppercase)
                    .foregroundStyle(Theme.muted)
                MathText(html: explainWhyHtml, fontSize: 15)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }

        Button {
            onContinue()
        } label: {
            Text(isLast ? "Finish" : "Next step")
                .font(Theme.Typography.emphasis)
                .frame(maxWidth: .infinity)
                .padding(.vertical, Theme.Space.m)
                .background(Theme.actionBg)
                .foregroundStyle(Theme.actionFg)
                .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))
        }
    }

    /// A calm feedback note for a wrong pick's rationale. Neutral by design (a
    /// hairline border, body text), never red, per the honesty rule.
    private func calmNote(_ html: String) -> some View {
        MathText(html: html, fontSize: 14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.vertical, Theme.Space.s)
            .padding(.horizontal, Theme.Space.m)
            .background(
                RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous)
                    .fill(Theme.elevated)
            )
            .overlay(
                RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous)
                    .strokeBorder(Theme.border, lineWidth: 1)
            )
    }
}

// MARK: - Preview

#if DEBUG
private let subproblemPreviewStep = TutorStep(
    index: 0,
    variantIndex: 0,
    prompt: "Find the limiting contact condition at the top of a vertical loop.",
    stemHtml: "A toy car is at the top of a frictionless vertical loop of radius \\(0.90\\,\\text{m}\\). "
        + "In the limiting case where it is just about to lose contact, what is the minimum speed at the top? "
        + "Use \\(g = 10\\,\\text{m/s}^2\\).",
    choices: [
        "\\(3.0\\,\\text{m/s}\\)",
        "\\(0\\,\\text{m/s}\\)",
        "\\(4.2\\,\\text{m/s}\\)",
        "\\(9.0\\,\\text{m/s}\\)",
        "\\(2.1\\,\\text{m/s}\\)",
    ]
)

/// The MCQ (open) and satisfied states in one scroll, so both are reviewable at
/// once, including the calm (never red) wrong-pick rationale.
private struct SubproblemPreviewGallery: View {
    @State private var pickA: String? = "C"
    @State private var pickB: String? = "A"

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Space.l) {
                Text("MCQ, wrong pick (calm, never red)")
                    .font(Theme.Typography.caption)
                    .foregroundStyle(Theme.muted)
                SubproblemCardView(
                    step: subproblemPreviewStep,
                    stepNumber: 1,
                    total: 3,
                    selected: $pickA,
                    phase: .mcq,
                    correctKey: nil,
                    rationaleHtml: "This uses \\(v^2 = 2gR\\), confusing the top-force condition with an energy drop.",
                    explainWhyHtml: "",
                    isLast: false,
                    onCheck: {},
                    onContinue: {}
                )

                Text("Satisfied, model rationale revealed")
                    .font(Theme.Typography.caption)
                    .foregroundStyle(Theme.muted)
                SubproblemCardView(
                    step: subproblemPreviewStep,
                    stepNumber: 3,
                    total: 3,
                    selected: $pickB,
                    phase: .done,
                    correctKey: "A",
                    rationaleHtml: "",
                    explainWhyHtml: "At the top, gravity supplies the centripetal force in the limiting case, "
                        + "so \\(mg = mv^2/R\\) and \\(v = \\sqrt{gR} = 3.0\\,\\text{m/s}\\).",
                    isLast: true,
                    onCheck: {},
                    onContinue: {}
                )
            }
            .padding(Theme.Space.l)
        }
        .background(Theme.canvas)
    }
}

#Preview("SubproblemCard light") {
    SubproblemPreviewGallery().preferredColorScheme(.light)
}

#Preview("SubproblemCard dark") {
    SubproblemPreviewGallery().preferredColorScheme(.dark)
}
#endif
