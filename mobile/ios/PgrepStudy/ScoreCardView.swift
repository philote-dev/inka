// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// The score card, ported from the desktop ScoreCard primitive: a number in its
// reserved hue, an 80% range, a how-sure read, last-updated, and an honest
// abstain when data is thin. Never a bare number (design/ux-foundation.md §6).

import SwiftUI

struct ScoreCardView: View {
    let kind: ScoreKind
    let value: ScoreValue
    let updated: Date?

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Space.s) {
            header
            if value.abstain {
                abstain
            } else {
                figure
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(Theme.Space.l)
        .background(Theme.surface)
        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous)
                .stroke(Theme.border, lineWidth: 1)
        )
    }

    private var header: some View {
        HStack(spacing: Theme.Space.s) {
            Circle()
                .fill(kind.fill)
                .frame(width: 10, height: 10)
            Text(kind.rawValue)
                .font(Theme.Typography.emphasis)
                .foregroundStyle(Theme.text)
            Spacer()
        }
    }

    private var figure: some View {
        VStack(alignment: .leading, spacing: Theme.Space.xs) {
            Text(Self.pct(value.point))
                .font(Theme.Typography.score)
                .foregroundStyle(kind.textTint)
            if let low = value.low, let high = value.high {
                Text("\(Self.pct(low)) to \(Self.pct(high)) likely")
                    .font(Theme.Typography.mono(12))
                    .foregroundStyle(Theme.muted)
            }
            HStack(spacing: Theme.Space.s) {
                Text(howSure)
                if let updated {
                    Text("·").foregroundStyle(Theme.muted)
                    Text(Self.updatedText(updated))
                }
            }
            .font(Theme.Typography.caption)
            .foregroundStyle(Theme.muted)
        }
    }

    private var abstain: some View {
        VStack(alignment: .leading, spacing: Theme.Space.xs) {
            Text("Not enough evidence yet")
                .font(Theme.Typography.emphasis)
                .foregroundStyle(Theme.muted)
            if let reason = value.reason {
                Text(reason)
                    .font(Theme.Typography.caption)
                    .foregroundStyle(Theme.muted)
            }
            Text(kind.caption)
                .font(Theme.Typography.caption)
                .foregroundStyle(Theme.muted)
        }
    }

    private var howSure: String {
        guard let low = value.low, let high = value.high else { return "" }
        switch high - low {
        case ..<0.06: return "Very sure"
        case ..<0.12: return "Fairly sure"
        case ..<0.20: return "Rough estimate"
        default: return "Uncertain"
        }
    }

    /// A 0..1 score shown on the 0..100 scale used across pgrep. "--" when nil.
    static func pct(_ value: Double?) -> String {
        guard let value else { return "--" }
        return String(Int((value * 100).rounded()))
    }

    static func updatedText(_ date: Date) -> String {
        let seconds = Date().timeIntervalSince(date)
        if seconds < 90 { return "Updated just now" }
        let minutes = Int(seconds / 60)
        if minutes < 60 { return "Updated \(minutes)m ago" }
        let hours = minutes / 60
        if hours < 24 { return "Updated \(hours)h ago" }
        return "Updated \(hours / 24)d ago"
    }
}
