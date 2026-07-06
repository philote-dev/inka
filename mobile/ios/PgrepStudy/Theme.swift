// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Native translation of the pgrep design tokens (ts/lib/sass/_pgrep.scss) for
// the iOS companion. Colors adapt to light/dark automatically via a dynamic
// UIColor provider, so views never thread the color scheme through by hand.
// Fonts use the system family (SF Pro is an approved UI face in
// design/ux-foundation.md §3.1) with tabular/monospaced numerals for the
// instrument-style figures, so no fonts need to be bundled.
//
// Reserved color meanings (design/ux-foundation.md §3.2): amber = Memory,
// blue = Performance, lilac = Readiness. Interactive chrome is monochrome, so
// the only meaning-bearing color on screen is the data.

import SwiftUI
import UIKit

extension Color {
    /// Build a Color from a 0xRRGGBB integer.
    init(hex: UInt32) {
        let r = Double((hex >> 16) & 0xFF) / 255.0
        let g = Double((hex >> 8) & 0xFF) / 255.0
        let b = Double(hex & 0xFF) / 255.0
        self.init(.sRGB, red: r, green: g, blue: b, opacity: 1.0)
    }

    /// A color that resolves to `light` or `dark` based on the active trait.
    static func dynamic(light: UInt32, dark: UInt32) -> Color {
        Color(UIColor { traits in
            traits.userInterfaceStyle == .dark ? UIColor(hex: dark) : UIColor(hex: light)
        })
    }
}

extension UIColor {
    fileprivate convenience init(hex: UInt32) {
        let r = CGFloat((hex >> 16) & 0xFF) / 255.0
        let g = CGFloat((hex >> 8) & 0xFF) / 255.0
        let b = CGFloat(hex & 0xFF) / 255.0
        self.init(red: r, green: g, blue: b, alpha: 1.0)
    }
}

/// The pgrep visual system, ported from the SCSS token set. Values mirror
/// `ts/lib/sass/_pgrep.scss` exactly so the two hosts read as one product.
enum Theme {
    // MARK: Neutrals (warm)

    static let canvas = Color.dynamic(light: 0xFBFAF8, dark: 0x262624)
    static let surface = Color.dynamic(light: 0xFFFFFF, dark: 0x302F2C)
    static let elevated = Color.dynamic(light: 0xF5F2EC, dark: 0x3A3835)
    static let border = Color.dynamic(light: 0xE8E4DA, dark: 0x45433E)
    static let text = Color.dynamic(light: 0x262624, dark: 0xECEAE3)
    static let muted = Color.dynamic(light: 0x6E6B64, dark: 0xA5A199)

    // MARK: Score hues (reserved data language)
    // Fills are identical in both themes; the text tint darkens for light mode.

    static let memory = Color(hex: 0xEBCB8B)
    static let memoryText = Color.dynamic(light: 0xA9752A, dark: 0xEBCB8B)
    static let performance = Color(hex: 0x81A1C1)
    static let performanceText = Color.dynamic(light: 0x5E81AC, dark: 0x81A1C1)
    static let readiness = Color(hex: 0xC4A7D6)
    static let readinessText = Color.dynamic(light: 0x7E6593, dark: 0xC4A7D6)

    // MARK: Monochrome interaction

    static let actionBg = Color.dynamic(light: 0x262624, dark: 0xECEAE3)
    static let actionFg = Color.dynamic(light: 0xFBFAF8, dark: 0x262624)
    static let focusRing = Color.dynamic(light: 0x262624, dark: 0xECEAE3)

    // MARK: State colors (separate set, never collide with the score language)

    static let success = Color(hex: 0xA3BE8C)
    static let caution = Color(hex: 0xD08770)
    static let error = Color(hex: 0xBF616A)

    /// Spacing on an 8pt grid (`--space-*`).
    enum Space {
        static let xs: CGFloat = 4
        static let s: CGFloat = 8
        static let m: CGFloat = 16
        static let l: CGFloat = 24
        static let xl: CGFloat = 32
        static let xxl: CGFloat = 40
        static let xxxl: CGFloat = 48
    }

    /// Corner radii (`--radius-*`).
    enum Radius {
        static let control: CGFloat = 10
        static let row: CGFloat = 12
        static let card: CGFloat = 16
        static let frame: CGFloat = 20
        static let pill: CGFloat = 999
    }

    /// Motion (`--duration-calm`), a calm spring in the 200-300ms band.
    enum Motion {
        static let calm: Double = 0.24
        static var spring: Animation { .spring(response: 0.32, dampingFraction: 0.82) }
    }

    /// Type ramp (`--text-*`). UI uses the system face; data uses monospaced
    /// digits so scores, ranges, and timers read like an instrument.
    enum Typography {
        static let caption = Font.system(size: 11)
        static let small = Font.system(size: 12)
        static let body = Font.system(size: 14)
        static let emphasis = Font.system(size: 16, weight: .semibold)
        static let content = Font.system(size: 17)
        static let title = Font.system(size: 24, weight: .semibold)
        static let greeting = Font.system(size: 26, weight: .semibold)

        /// Large instrument figure (the score number), tabular so it does not
        /// jitter as it updates.
        static let score = Font.system(size: 40, weight: .semibold).monospacedDigit()
        /// The compact score figure for the Home three-across row.
        static let scoreCompact = Font.system(size: 26, weight: .semibold).monospacedDigit()
        /// Inline data/numerals (ranges, counts, timers).
        static func mono(_ size: CGFloat, weight: Font.Weight = .regular) -> Font {
            Font.system(size: size, weight: weight).monospaced()
        }
    }
}

/// The learner's theme choice, applied through SwiftUI's `preferredColorScheme`.
/// Stored per device in UserDefaults (a device-level UI preference). Desktop
/// keeps its theme in the synced collection config; on a phone a per-device
/// choice is the sensible equivalent, so this is not written to the collection.
enum AppTheme: String, CaseIterable, Identifiable {
    case system
    case light
    case dark

    /// The UserDefaults key backing the choice (@AppStorage in App + Settings).
    static let storageKey = "pgrep.theme"

    var id: String { rawValue }

    var label: String {
        switch self {
        case .system: return "System"
        case .light: return "Light"
        case .dark: return "Dark"
        }
    }

    /// nil means "follow the system", so a fresh install never forces a choice.
    var colorScheme: ColorScheme? {
        switch self {
        case .system: return nil
        case .light: return .light
        case .dark: return .dark
        }
    }
}

/// The three pgrep scores, each carrying its reserved hue.
enum ScoreKind: String, CaseIterable {
    case memory = "Memory"
    case performance = "Performance"
    case readiness = "Readiness"

    var fill: Color {
        switch self {
        case .memory: return Theme.memory
        case .performance: return Theme.performance
        case .readiness: return Theme.readiness
        }
    }

    var textTint: Color {
        switch self {
        case .memory: return Theme.memoryText
        case .performance: return Theme.performanceText
        case .readiness: return Theme.readinessText
        }
    }

    /// One-line "what it answers", matching the desktop cards.
    var caption: String {
        switch self {
        case .memory: return "Can you recall it"
        case .performance: return "Can you do the problems"
        case .readiness: return "Are you ready for the exam"
        }
    }
}
