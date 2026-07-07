# Manifold · Top-down map — design handoff

The labeled 2D top-down projection of the pgrep knowledge manifold: the user
looks straight down at their knowledge like terrain on a topographic map.
Contours are performance, glow is memory, holes are knowledge gaps, the
footprint is the exam blueprint. Same surface data as the 3D wireframe —
this is the second projection of one model, and the small-screen default.

## Files

- `Manifold Top View.dc.html` — dark reference page, fully self-contained
- `Manifold Top View Light.dc.html` — light twin
- `manifold-core.js` — zero-dependency renderer (surface math + `drawContour`
  + `drawManifold`). ES module, no build step required.
- `PHILOSOPHY.md` — why the map looks and behaves the way it does
- `TECHNICAL-SPEC.md` — data contract, stat mapping, render pipeline,
  overlay spec, theming, interaction, production notes
- `support.js` — mockup runtime only; not part of the handoff

## Quick start

Open either `.dc.html` page in a browser. Only external fetch is Google
Fonts (Inter + JetBrains Mono); production self-hosts the same families
via Fontsource.

Tweakable on the reference pages: `glow` (render intensity), `grid`
(sampling density), `showCallouts` (label overlay on/off).

## What the app builds

One `surface` object per user, derived from live stats (see
TECHNICAL-SPEC § Stat mapping). Feed it to:

- **3D wireframe** — Three.js, the Home hero (emotional overview)
- **Top-down map** — this package. D3 7 (`d3-contour`) in production, or
  port `drawContour` as-is; it has no dependencies. Default on mobile and
  the fallback wherever WebGL is unavailable.

Every mark on the map traces to a statistic. The perf numbers on the
reference pages derive from peak heights; the mem values are illustrative
placeholders — wire both to live stats at integration.
