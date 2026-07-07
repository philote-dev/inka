// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// The end-of-session consolidation screen, a native port of
// ts/lib/components/SessionSynthesis.svelte shown when the interleaved study
// session finishes. Truth first, warmth from reframing: the first-try score is
// stated plainly and reframed honestly, then per-topic bars and the pattern
// cards. The centre is patterns, not a question-by-question replay, because the
// pattern is the transferable unit. Presentational: it renders the payload the
// SessionSynthesizer computed from the finished session's clean commits.
//
// Honesty voice (design/ux-foundation.md): a miss is never red. Topic bars fill
// in the Performance hue over a neutral track, so a low bar reads as "more to do
// here", not as an error state.

import SwiftUI

struct SessionSynthesisView: View {
    let synthesis: SessionSynthesis
    /// Cards reviewed alongside the problems this session. The desktop splits
    /// Cards and Problems into separate doors, so its synthesis is problems-only;
    /// the phone weaves them, so this adds an honest line for the memory work.
    var cardsReviewed: Int = 0
    /// The single exit: begin a fresh sitting. The session lives in a tab, so
    /// there is no modal to close; starting again is the clear way to move on.
    var onDone: () -> Void

    /// Short topic labels, ported from the Svelte LABELS map (not the longer
    /// launcher labels). Falls back to the de-slugged name.
    private static let labels: [String: String] = [
        "mechanics": "Mechanics",
        "electromagnetism": "E&M",
        "quantum": "Quantum",
        "thermodynamics": "Thermo",
        "atomic": "Atomic",
        "optics_waves": "Optics & waves",
        "special_relativity": "Relativity",
        "lab": "Lab methods",
        "specialized": "Specialized",
    ]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Space.l) {
                pill
                scoreHeader
                if !synthesis.reframe.isEmpty {
                    Text(synthesis.reframe)
                        .font(Theme.Typography.body)
                        .foregroundStyle(Theme.muted)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if !synthesis.byTopic.isEmpty {
                    topicSection
                }
                if !synthesis.patterns.isEmpty {
                    patternSection
                }
                footer
            }
            .padding(.bottom, Theme.Space.l)
        }
    }

    // MARK: Header

    private var pill: some View {
        Text("Session complete")
            .font(Theme.Typography.caption)
            .foregroundStyle(Theme.performanceText)
            .padding(.horizontal, Theme.Space.m)
            .padding(.vertical, Theme.Space.xs + 2)
            .overlay(
                RoundedRectangle(cornerRadius: Theme.Radius.pill, style: .continuous)
                    .stroke(Theme.performance.opacity(0.45), lineWidth: 1)
            )
    }

    private var scoreHeader: some View {
        VStack(alignment: .leading, spacing: Theme.Space.s) {
            Text("Session synthesis")
                .font(Theme.Typography.caption)
                .textCase(.uppercase)
                .foregroundStyle(Theme.muted)
            HStack(alignment: .firstTextBaseline, spacing: Theme.Space.s) {
                Text("\(synthesis.score.correct) / \(synthesis.score.total)")
                    .font(Theme.Typography.score)
                    .foregroundStyle(Theme.text)
                Text(scoreMeta)
                    .font(Theme.Typography.body)
                    .foregroundStyle(Theme.muted)
            }
        }
    }

    private var scoreMeta: String {
        var parts = ["correct", durationLabel]
        if cardsReviewed > 0 {
            parts.append("\(cardsReviewed) \(cardsReviewed == 1 ? "card" : "cards") reviewed")
        }
        return parts.joined(separator: " · ")
    }

    private var durationLabel: String {
        synthesis.durationMin >= 1 ? "\(synthesis.durationMin) min" : "under a minute"
    }

    // MARK: Topic bars

    private var topicSection: some View {
        VStack(alignment: .leading, spacing: Theme.Space.m) {
            sectionHeading("By topic")
            VStack(spacing: Theme.Space.s + Theme.Space.xs) {
                ForEach(synthesis.byTopic, id: \.topic) { topic in
                    topicRow(topic)
                }
            }
        }
    }

    private func topicRow(_ topic: SynthesisTopic) -> some View {
        HStack(spacing: Theme.Space.m) {
            Text(label(topic.topic))
                .font(Theme.Typography.body)
                .foregroundStyle(Theme.text)
                .lineLimit(1)
                .truncationMode(.tail)
                .frame(width: 108, alignment: .leading)
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(Theme.border)
                    Capsule()
                        .fill(Theme.performance)
                        .frame(width: geo.size.width * fraction(topic))
                }
            }
            .frame(height: 6)
            Text("\(topic.correct) / \(topic.total)")
                .font(Theme.Typography.mono(12))
                .foregroundStyle(Theme.muted)
                .frame(width: 46, alignment: .trailing)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(label(topic.topic)): \(topic.correct) of \(topic.total) correct")
    }

    private func fraction(_ topic: SynthesisTopic) -> Double {
        topic.total > 0 ? Double(topic.correct) / Double(topic.total) : 0
    }

    // MARK: Pattern cards

    private var patternSection: some View {
        VStack(alignment: .leading, spacing: Theme.Space.m) {
            sectionHeading("Patterns across the session")
            VStack(spacing: Theme.Space.s) {
                ForEach(synthesis.patterns, id: \.title) { pattern in
                    patternCard(pattern)
                }
            }
        }
    }

    private func patternCard(_ pattern: SynthesisPattern) -> some View {
        VStack(alignment: .leading, spacing: Theme.Space.s) {
            HStack(alignment: .top, spacing: Theme.Space.m) {
                Text(pattern.title)
                    .font(Theme.Typography.emphasis)
                    .foregroundStyle(Theme.text)
                    .frame(maxWidth: .infinity, alignment: .leading)
                countChip(pattern)
            }
            if !pattern.evidence.isEmpty {
                MathText(html: pattern.evidence, fontSize: 14)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .padding(Theme.Space.m)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.surface)
        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous)
                .stroke(Theme.border, lineWidth: 1)
        )
    }

    private func countChip(_ pattern: SynthesisPattern) -> some View {
        let save = pattern.kind == .save
        return Text(countLabel(pattern))
            .font(Theme.Typography.mono(11))
            .foregroundStyle(save ? Theme.performanceText : Theme.muted)
            .padding(.horizontal, Theme.Space.s + Theme.Space.xs)
            .padding(.vertical, Theme.Space.xs)
            .overlay(
                RoundedRectangle(cornerRadius: Theme.Radius.pill, style: .continuous)
                    .stroke(save ? Theme.performance.opacity(0.5) : Theme.border, lineWidth: 1)
            )
            .fixedSize()
    }

    private func countLabel(_ pattern: SynthesisPattern) -> String {
        let noun = pattern.kind == .save ? "save" : "miss"
        let plural = pattern.kind == .save ? "saves" : "misses"
        return "\(pattern.count) \(pattern.count == 1 ? noun : plural)"
    }

    // MARK: Footer

    private var footer: some View {
        VStack(alignment: .leading, spacing: Theme.Space.m) {
            Text("Your next session leans on these patterns.")
                .font(Theme.Typography.caption)
                .foregroundStyle(Theme.muted)
            Button(action: onDone) {
                Text("Start again")
                    .font(Theme.Typography.emphasis)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, Theme.Space.m)
                    .background(Theme.actionBg)
                    .foregroundStyle(Theme.actionFg)
                    .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))
            }
        }
        .padding(.top, Theme.Space.s)
    }

    // MARK: Helpers

    private func sectionHeading(_ text: String) -> some View {
        Text(text)
            .font(Theme.Typography.caption)
            .textCase(.uppercase)
            .foregroundStyle(Theme.muted)
    }

    private func label(_ slug: String) -> String {
        Self.labels[slug] ?? slug.replacingOccurrences(of: "_", with: " ")
    }
}
