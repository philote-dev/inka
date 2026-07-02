# pgrep design system

pgrep is a Physics GRE study app built on the Anki engine. Its personality is an honest measuring instrument that renders physics beautifully. Element craft in the spirit of Claude, Linear, and Apple. Calm, precise, content first, nothing decorative.

**One line.** An honest physics instrument that renders your readiness beautifully.

## Sources

- GitHub repo `philote-dev/inka` (the Anki fork). Frontend in `ts/` (Svelte 5 + TypeScript, SCSS variable theming in `ts/lib/sass`, dark via the `.night-mode` class).
- `docs/pgrep/planning/ux-foundation.md` in that repo (imported into this project at the same path). The authoritative UX foundation.
- Concept renders in `docs/pgrep/planning/assets/ux/` (dark home, wireframe manifold, and more). Copies of the key ones live in `assets/reference/`.
- Live mockups built in this project. `Home.dc.html`, `Study.dc.html`, `Cards.dc.html`, `Library.dc.html`, `Mobile.dc.html`.

## Build target

Production is Svelte 5 with SCSS and CSS-variable theming. Not React, not Tailwind. The React components here are mockup primitives, kept framework-neutral and token-driven so they map one-to-one onto Svelte. Charts are D3 7. Math is MathJax 3. The 3D manifold is Three.js with a 2D D3 contour fallback. Mobile is native SwiftUI and Compose, a native translation of the same tokens.

## The reserved color language

Amber `#EBCB8B` means Memory. Blue `#81A1C1` means Performance. Lilac `#C4A7D6` means Readiness. These three hues are a data language and are never used for decoration. State colors (success `#A3BE8C`, caution `#D08770`, error `#BF616A`) are a separate set and never collide with the score language. Everything interactive (buttons, links, focus rings) is monochrome, so the only meaning-bearing color on screen is the data.

## The honesty rule

Every score shows a point number in tabular figures, a likely range ("Likely 68 to 77"), a how-sure read ("Fairly sure"), and a last-updated line ("Updated 2h ago"). When data is thin the score abstains ("Not enough evidence yet"), names what is missing, and links to it. Readiness is gated by coverage. Components in this system bake that anatomy in; do not strip it to a bare number.

## Content fundamentals

- Voice is an honest instrument, lightly human. Truth first. Warmth comes from reframing, never from empty praise.
- **No em-dashes. No colon-heavy phrasing.** Periods, commas, and short labels.
- Sentence case everywhere, including buttons ("Start session", "Show the step"). Tiny labels may be uppercase with tracking ("FAIRLY SURE" style captions).
- Second person for the learner, first person plural for the system. "Write one card in your own words. We scale the rest in your style."
- Never flatter a right answer, never punish a wrong one. A wrong commit gets "Your answer, not correct" in calm blue, never red.
- Numbers never stand alone. Ranges read as "68 to 77", times as "About 25 min", updates as "Updated 2h ago".
- Reframe struggle as progress. "Working it out yourself is the point." "In-session accuracy understates your learning."
- No emoji, ever.

## Visual foundations

- **Neutrals are warm.** Light canvas `#FBFAF8`, dark canvas `#262624` (a warm grey, not black). Cards sit one step lighter (`#FFFFFF` / `#302F2C`) behind a 1px hairline border and a very soft shadow.
- **Adaptive theme.** Light and dark are both first class. Mockups default to dark. Dark is the `.night-mode` scope (also `[data-theme="dark"]`).
- **Shape.** Squircle cards. Radii 10px controls, 12px rows, 16px cards, 20px hero frames, pills for chips. 8pt spacing grid, generous negative space, one primary action per screen.
- **Type.** Inter for UI (weights 400/500/600, tight tracking on headings). JetBrains Mono for scores, timers, ranges, and dense data. Tabular lining figures on every number (`font-variant-numeric: tabular-nums`). Math is MathJax, set like a good textbook at 16 to 22px.
- **Backgrounds.** Flat canvas color. No photography, no textures, no decorative gradients. The only glow allowed is the manifold's soft under-light (score hues at ~7% alpha).
- **The manifold** is the one piece of imagery. A clean 3D wireframe surface (amber to lilac to blue across it, holes for gaps), an instrument readout, never photoreal terrain. Shared renderer in `manifold.js` (root) and `components/viz/manifold-core.js`. It is fully data driven (bumps, dips, holes, glows, labels).
- **Motion.** Calm spring, 200 to 300ms, `cubic-bezier(0.32, 0.72, 0, 1)`. Confident, not bouncy. Nothing blocks the screen for more than 100ms. The manifold morphs smoothly as stats change.
- **Hover.** Borders lighten one step (border to muted), surfaces take a faint wash (`--hover-wash`), primary buttons brighten (`#ECEAE3` to `#FFFFFF` on dark). Press states compress nothing; color only.
- **Focus.** Monochrome ring (`--focus-ring`), 2px offset. Never a colored glow.
- **Transparency and blur.** Tinted borders use rgba of the accent at 35 to 45%. No backdrop blur anywhere.
- **Selection in problems** is a thin 1.5px blue outline plus a 6% blue wash. Committed-wrong is the same row at 62% opacity with a blue tag. Nothing red during learning.

## Iconography

- Outline icons, 1.5px stroke, round caps and joins, drawn on 16 to 20px grids, always `currentColor`. Production imports **Lucide** (`lucide-static`) via the fork's `.svg?component` pattern. Mockups inline equivalent hand-kept SVGs (see any `.dc.html`).
- Score glyphs are fixed. Layers = Memory, target = Performance, gauge = Readiness. They take the score hue; all other icons stay monochrome.
- The logo is the nested-contour blob mark (`assets/logo-ref.png`), a miniature knowledge map distilled from a manifold, kept as a clean 2D glyph that survives at 16px. An inline SVG version lives in the mockups' nav rails.
- No emoji, no unicode-as-icon.

## Component inventory

From ux-foundation.md section 8, built under `components/`:

- `score/ScoreCard` — number, range, how-sure, last-updated, abstain state.
- `study/StudyFrame` — minimal session chrome (progress, topic chip, close).
- `study/ChoiceList` — five choices A to E, monochrome default, blue select.
- `study/HintRung` — Break it down card, hint budget, never leaks the answer.
- `study/GradeBar` — FSRS grades Again / Hard / Good / Easy with intervals.
- `progress/CoverageBar` — segmented per-topic coverage, gates Readiness.
- `progress/ReliabilityDiagram` — predicted vs observed, diagonal, Brier.
- `viz/Manifold` — the wireframe knowledge manifold (canvas, data driven).

**Intentional additions.** `core/Button` and `core/Chip`, the two primitives every screen above composes; the foundation uses them implicitly.

## Index

- `styles.css` — global entry. Imports `tokens/` (fonts, colors, typography, shape, motion).
- `tokens/` — CSS custom properties, light `:root` + dark `.night-mode`.
- `components/` — core, score, study, progress, viz (JSX + d.ts + prompt.md + specimen card each).
- `guidelines/` — foundation specimen cards for the Design System tab.
- `ui_kits/pgrep/` — index into the live desktop and mobile mockup screens.
- `assets/` — logo and reference renders.
- `docs/pgrep/planning/ux-foundation.md` — the imported source foundation.
- `manifold.js` — shared data-driven manifold renderer (root copy used by the mockups).
- `SKILL.md` — agent skill entry point.
