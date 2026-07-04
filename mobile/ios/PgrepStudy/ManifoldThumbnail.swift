// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// The knowledge-manifold thumbnail for the mobile Home glance. This is the 2D
// wireframe rendering (design/ux-foundation.md §5 calls it the reliable
// fallback and the small-screen default), drawn with a plain SwiftUI Canvas so
// it always renders, with no WebGL/SceneKit dependency. A faint amber ridge
// nods at Memory, the one live score; it is decorative here, not data-bearing.

import Foundation
import SwiftUI

struct ManifoldThumbnail: View {
    var body: some View {
        Canvas { context, size in
            let n = 14
            let cx = size.width / 2
            let cy = size.height * 0.60
            let sx = size.width / 2.7
            let sy = size.height / 2.7
            let heightScale = size.height * 0.34

            func height(_ u: Double, _ v: Double) -> Double {
                func bump(_ u0: Double, _ v0: Double, _ spread: Double) -> Double {
                    let du = u - u0, dv = v - v0
                    return exp(-(du * du + dv * dv) / spread)
                }
                // Two gentle peaks and one dip ("a hole", honest by construction).
                return 0.55 * bump(0.33, 0.42, 0.05)
                    + 0.34 * bump(0.70, 0.66, 0.08)
                    - 0.22 * bump(0.74, 0.28, 0.028)
            }

            func project(_ i: Int, _ j: Int) -> CGPoint {
                let u = Double(i) / Double(n)
                let v = Double(j) / Double(n)
                let h = height(u, v)
                let x = cx + (u - v) * sx
                let y = cy + (u + v) * sy * 0.5 - h * heightScale
                return CGPoint(x: x, y: y)
            }

            for i in 0 ... n {
                var along = Path()
                var across = Path()
                for j in 0 ... n {
                    let p1 = project(i, j)
                    let p2 = project(j, i)
                    if j == 0 {
                        along.move(to: p1)
                        across.move(to: p2)
                    } else {
                        along.addLine(to: p1)
                        across.addLine(to: p2)
                    }
                }
                context.stroke(along, with: .color(Theme.memory.opacity(0.45)), lineWidth: 1)
                context.stroke(across, with: .color(Theme.border), lineWidth: 1)
            }
        }
        .background(Theme.elevated)
        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous)
                .stroke(Theme.border, lineWidth: 1)
        )
        .accessibilityLabel("Knowledge manifold overview")
    }
}
