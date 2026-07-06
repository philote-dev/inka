// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// The score card, ported from the desktop ScoreCard primitive: a number in its
// reserved hue, an 80% range, a how-sure read, last-updated, and an honest
// abstain when data is thin. Never a bare number (design/ux-foundation.md §6).

import SwiftUI

/// How a score's figure reads: a 0..1 fraction shown on the 0..100 scale
/// (Memory, Performance), or a whole scaled score on the 200-990 PGRE band
/// (Readiness), which must never be multiplied by 100.
enum ScoreScale {
    case fraction
    case scaled
}

struct ScoreCardView: View {
    let kind: ScoreKind
    let value: ScoreValue
    let updated: Date?
    /// Figure formatting; defaults to the 0..100 percentage used by Memory and
    /// Performance so existing call sites are unchanged.
    var scale: ScoreScale = .fraction
    /// A how-sure read supplied by the caller (Readiness reads out its coverage
    /// instead of an interval width). Falls back to the interval-width read.
    var howSureDetail: String? = nil

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
            Text(figureText(value.point))
                .font(Theme.Typography.score)
                .foregroundStyle(kind.textTint)
            if let range = rangeText {
                Text(range)
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

    /// The main figure, formatted for the score's scale.
    private func figureText(_ value: Double?) -> String {
        switch scale {
        case .fraction: return Self.pct(value)
        case .scaled: return Self.whole(value)
        }
    }

    /// The 80% range line, formatted for the score's scale, or nil when absent.
    private var rangeText: String? {
        guard let low = value.low, let high = value.high else { return nil }
        switch scale {
        case .fraction: return "\(Self.pct(low)) to \(Self.pct(high)) likely"
        case .scaled: return "\(Self.whole(low)) to \(Self.whole(high)) band"
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
        if let howSureDetail { return howSureDetail }
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

    /// A whole score shown as-is (the 200-990 Readiness band). "--" when nil.
    static func whole(_ value: Double?) -> String {
        guard let value else { return "--" }
        return String(Int(value.rounded()))
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

/// The compact score card for the Home three-across row: the reserved-hue dot and
/// name, the figure in its hue, and a tight 80% range under it. It still abstains
/// honestly on thin data (a dash, never a fabricated number), just in a smaller
/// footprint than the full `ScoreCardView` used on Progress.
struct CompactScoreCard: View {
    let kind: ScoreKind
    let value: ScoreValue
    var scale: ScoreScale = .fraction
    var loading = false

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Space.xs) {
            HStack(spacing: 5) {
                Circle()
                    .fill(kind.fill)
                    .frame(width: 8, height: 8)
                Text(kind.rawValue)
                    .font(Theme.Typography.caption)
                    .foregroundStyle(Theme.muted)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
            }
            if loading {
                ProgressView()
                    .controlSize(.small)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, Theme.Space.xs)
            } else if value.abstain {
                Text("--")
                    .font(Theme.Typography.scoreCompact)
                    .foregroundStyle(Theme.muted)
                Text("Not yet")
                    .font(Theme.Typography.caption)
                    .foregroundStyle(Theme.muted)
            } else {
                Text(figure)
                    .font(Theme.Typography.scoreCompact)
                    .foregroundStyle(kind.textTint)
                    .lineLimit(1)
                    .minimumScaleFactor(0.6)
                Text(range)
                    .font(Theme.Typography.mono(10))
                    .foregroundStyle(Theme.muted)
                    .lineLimit(1)
                    .minimumScaleFactor(0.6)
            }
        }
        .frame(maxWidth: .infinity, minHeight: 78, alignment: .leading)
        .padding(.horizontal, Theme.Space.m)
        .padding(.vertical, Theme.Space.s)
        .background(Theme.surface)
        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous)
                .stroke(Theme.border, lineWidth: 1)
        )
    }

    private var figure: String {
        switch scale {
        case .fraction: return ScoreCardView.pct(value.point)
        case .scaled: return ScoreCardView.whole(value.point)
        }
    }

    private var range: String {
        guard let low = value.low, let high = value.high else { return " " }
        switch scale {
        case .fraction: return "\(ScoreCardView.pct(low))-\(ScoreCardView.pct(high))"
        case .scaled: return "\(ScoreCardView.whole(low))-\(ScoreCardView.whole(high))"
        }
    }
}
