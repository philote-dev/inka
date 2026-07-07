# Technical spec — top-down manifold map

## Architecture

One `surface` object per user, derived from live stats. Two consumers:

- `drawManifold(canvas, opts)` — 3D wireframe (Three.js in production)
- `drawContour(canvas, opts)` — this map (D3 7 `d3-contour` in production,
  already in the stack via Anki's stats graphs; or port this file — it has
  zero dependencies)

Both live in `manifold-core.js`. The canvas draws terrain only; all text
is real DOM positioned from anchors the renderer returns.

## Surface data contract

```js
surface = {
  boundary: [a0, a3, p3, a2, p2], // blob radius harmonics: R(θ) = a0 + a3·cos(3θ+p3) + a2·cos(2θ+p2)
  bumps:  [{ x, y, h, s }],       // topic peaks. h = performance, s = footprint
  dips:   [{ x, y, h, s }],       // rim sinks around gaps
  holes:  [{ x, y, rx, ry, rot }],// knowledge gaps — no data, no surface
  glows:  [{ x, y, c }],          // memory under-glow, rgb string
  labels: [{ name, x, y, dx, dy, tf }] // 3D-view callout placements
}
```

Coordinates are unit surface space (blob radius ≈ 1). `DEFAULT_SURFACE` is
the compact 4-peak embed form; `FULL_SURFACE` is the 9-unit syllabus for
the Home hero.

## Stat mapping (app → surface)

- `bump.h` ← topic performance, scaled so best topic ≈ 0.55. Readout
  `perf` = the topic's real 0–100 performance score.
- `bump.s` ← exam-blueprint weight of the topic (footprint area).
- `glows[].c` ← the reserved score hues (`SCORE_COLORS`): amber memory
  `235,203,139`, blue performance `129,161,193`, lilac readiness
  `196,167,214`. Glow placement follows the topic's leading statistic.
- `holes` ← coverage gaps: subtopics with no/low attempts. Size tracks the
  subtopic's blueprint share. Each hole pairs a `dip` at the same x,y so
  the rim sinks.
- `boundary` ← overall exam blueprint; total footprint is fixed, so growth
  in one region is real, not rescaled away.

## Render pipeline (top view)

1. **Glow underlay** — radial gradient per glow source (α ≈ 0.08·glow
   dark, 0.12 light).
2. **Domain edges** — boundary outline (1px, `rgba(165,161,153,.3)` dark /
   `rgba(110,107,100,.4)` light); hole rims dashed `3 4`.
3. **Contours** — marching squares over an n×n sample of `height(x,y)`,
   levels `[0.05, 0.1, 0.16, 0.22, 0.29, 0.36]`, `indexEvery: 3` → every
   3rd level draws 1.6px (index contour), others 1px. Stroke color from
   `colorAt(x,y)` (region hue), α ramps with level.
4. **Anchors** — returns `{ peaks, gaps }` in canvas px for the overlay.

```js
const out = drawContour(canvas, { W: 560, H: 560, S: 196, dpr: 2,
  glow: 0.85, grid: 96, indexEvery: 3, theme });
// out.peaks: [{ x, y, h }]  out.gaps: [{ x, y, rx, ry, rot }]
```

## Overlay spec (DOM/SVG, never canvas text)

- **Summit marker**: 2.5px filled dot + 7px ring at 50% opacity, both in
  the region tint.
- **Peak callout**: leader line 1px (`#6E6B64` dark / `#A5A199` light) from
  summit to label. Label = topic name 13px/500 in region tint over
  `perf NN · mem NN` 10px mono muted.
- **Gap callout**: dashed `3 3` leader + 3px hollow datum circle at hole
  center. Label = subtopic name 13px/500 ink over coverage note 10px mono
  ("gap · no attempts", "gap · 3 of 41 seen").
- **Region tint**: `colorAt(x,y,theme)` mixed toward ink — 35% toward
  `#ECEAE3` on dark, 18% toward `#262624` on light.
- **Placement**: labels sit outside the rim, anchored by
  `translate(0|-100%, -50%)`; offsets are tuned at S = 140 and scale by
  `S/140`. Production should auto-place radially outward from the summit
  along the vector from blob center, then resolve collisions.
- **Legend** (mono 10px muted): contour = performance (every 3rd indexed);
  dashed rim = knowledge gap; under-glow = memory; outer rim = blueprint
  weight.

## Theming

Dark: page `#1B1A19`, card `#262624`, border `#45433E`, text `#ECEAE3`,
muted `#A5A199`. Light: page `#EFECE6`, card `#FBFAF8`, inset `#F5F2EC`,
border `#E8E4DA`, text `#262624`, muted `#6E6B64`. Pass `theme: 'light'`
to the renderer — it swaps the palette ramp for paper-legible ink variants
and re-weights fills. Fonts: Inter (UI) + JetBrains Mono (data), Fontsource
variable packages in production.

## Interaction (production)

- **Tap a region → topic drill** (the Focus drill entry). Hit-test in
  surface space: invert `x = (px − W/2)/S`, then nearest bump within its
  `s` radius, or `inHole(surface, x, y)` for gaps.
- **Hover** (desktop): raise the region's callout to full opacity, dim
  others to 60%; cursor pointer inside the rim.
- **Callouts are buttons**: real DOM, keyboard-focusable, Enter drills.
- **Canvas is decorative**: `aria-hidden`, with the callout list as the
  accessible structure. Provide a plain table of topic / perf / mem /
  coverage as the text alternative.
- **Reduced motion**: no draw-in animation; render final frame.

## Svelte integration sketch

```svelte
<canvas bind:this={cv} aria-hidden="true"></canvas>
{#each anchors.peaks as p, i}
  <button class="callout" style="left:{p.x}px; top:{p.y}px"
    on:click={() => drill(topics[i])}> … </button>
{/each}
```

`$effect`: redraw on stats change or theme flip; `devicePixelRatio`-aware
backing store (mock uses 2×). The mock pages also expose `glow`, `grid`,
`showCallouts` as knobs — useful ranges: glow 0.4–1.2, grid 48–144.
