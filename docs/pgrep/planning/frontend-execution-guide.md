# pgrep Frontend Execution Guide (regenerated)

This regenerates the runbook after a repo resync. It reflects the current, real state: the pgrep L0/L1/L2 engine work is committed (branches `l0-build-foundation`, `l1-rust-selector`, `l2-core`, merged to `main`), and the UI work is layered on `pgrep-ui-design`.

## Current state (verified)

**Committed shell (yours, on this branch):**
- `ts/routes/pgrep/lib/bridge.ts` - `pgrepCall(fn, args)` POSTs JSON to `/_anki/<fn>` with content type `application/binary` ("Channel B", per `l2-api-contract.md`). This is the real data path, not `@generated/backend`.
- `ts/routes/pgrep/+layout.ts` - client-only (`ssr=false`, `prerender=false`).
- Nested routes `ts/routes/pgrep/{study,progress,diagnostic}/+page.svelte`. Nested works for in-app client navigation from `/pgrep`; only a full page load straight to a nested URL breaks (SvelteKit relative base path).

**UI work (mine, staged/on disk):**
- Tokens: `ts/lib/sass/_pgrep.scss` (scoped `.pgrep`, matches the export exactly).
- Renderer: `ts/lib/pgrep/manifold.ts` (`drawManifold`, `DEFAULT_SURFACE`, `FULL_SURFACE`, `SCORE_COLORS`, and `buildSurface(topics)` that maps stats to a surface).
- Components: `ts/lib/components/ScoreCard.svelte`, `Manifold.svelte`.
- Home: `ts/routes/pgrep/+page.svelte` (manifold hero + three score cards + Today) and `+layout.svelte` (fonts + tokens + `.pgrep` shell). These **overwrote** your scaffold `+page.svelte`/`+layout.svelte` (originals recoverable from `HEAD`).
- Manifold lab: `ts/routes/pgrep-lab/*` (proves data-driven behavior).
- `qt/aqt/mediasrv.py` - registered `pgrep-lab` and the planned `pgrep-*` surfaces in `is_sveltekit_page`.

**Verified live in Anki:** Home renders in light and dark, the manifold redraws on theme flip, and the lab proves performance->height, coverage->holes, leading score->hue.

## Lost and recovery

- Recovered from commit `83b30e6ff`: `ux-foundation.md` + `assets/ux/*.png` (restored to the tree).
- Not in history, need re-creation: `claude-design-prompts.md` (regenerate from the design decisions), `frontend-execution-guide.md` (this file), and the `design/` Claude Design export (re-export from Claude Design; the design system is saved there. Note the core of it is already ported into the code above).

## Reconciliation plan (my UI into your shell)

1. **Layout:** keep your `+layout.ts` (client-only). Fold my `.pgrep` wrapper + font/token imports into the pgrep layout so both the config and the styling shell coexist. Check `git show HEAD:ts/routes/pgrep/+layout.svelte` for anything of yours to preserve.
2. **Home:** keep my `+page.svelte` UI, but replace its mock data with `pgrepCall(...)` in a `+page.ts` load (per `l2-api-contract.md`), so the scores and the manifold `surface` come from the engine via `buildSurface`.
3. **Nested surfaces:** restyle your `study`/`progress`/`diagnostic` pages with the pgrep components (StudyFrame, ChoiceList, HintRung, CoverageBar, ReliabilityDiagram) as they get built.
4. **Navigation:** the nav rail links use client-side navigation to the nested routes (works around the base-path issue).

## Gotchas (learned)

- **Register every top-level pgrep page** in `is_sveltekit_page` in `qt/aqt/mediasrv.py`, then relaunch with `just run` (Python change; a web rebuild is not enough).
- **Rebuild web** after UI edits with `just rebuild-web` (about 10s, auto-reloads open pages). Serve at `http://127.0.0.1:40000/<page>`.
- **Cache:** the webview caches; disable cache or add a query buster when checking a change.
- **Licenses:** run `just fix-minilints` (needs staged changes) before `just check` to record the new package licenses.

## Dependencies added

`three`, `lucide-static`, `@fontsource-variable/inter`, `@fontsource-variable/jetbrains-mono`, `@types/three` (dev). All conflict-checked, all AGPL-compatible.

## Manifold lab (3D upgrade, done)

The lab is now the interactive proving ground for the manifold, not just static tiles.

- `ts/lib/pgrep/manifold3d.ts` - the production Three.js renderer. Consumes the exact same `Surface` as the 2D `manifold.ts` and reuses its math (`height` -> vertex Y, `boundaryR`+`inHole` -> which grid cells/edges exist so holes are real mesh gaps, `colorAt` -> per-vertex score hue, `glows` -> soft floor discs). Three layers, all `depthWrite:false` and painter-ordered like the 2D canvas: (1) a translucent color-shell `Mesh` with itemSize-4 RGBA vertex colors (per-vertex alpha fades in the valleys and rim, the "loose color fitting"; `USE_COLOR_ALPHA` confirmed at three build line 7682), (2) the vertex-colored `LineSegments` wireframe, (3) rim `LineLoop`s. `OrbitControls` (drag to orbit, scroll to zoom, optional calm auto-rotate). Topic labels: `computeLabels()` projects each anchor to pixels every frame the camera/surface moves and clamps the box into the viewport, delivered via an `onLabels` callback. Handle API: `update(surface, theme)`, `setShape({grid, heightScale, glow})`, `setAutoRotate`, `resize`, `resetView`, `dispose`. Colors go through `Color.setRGB(..., SRGBColorSpace)` so the default sRGB output matches the 2D canvas exactly.
- `ts/lib/components/Manifold3D.svelte` - wrapper. Client-only (`onMount`), disposes on destroy, MutationObserver on `.night-mode` re-themes, reactive to `surface`/`grid`/`heightScale`/`autoRotate`. Renders the HTML label + leader-line overlay from `onLabels` (a `.stage` div holds the canvas; the overlay sits above it, `pointer-events:none`). Props include `showLabels` (default true). Exposes `resetView()`.
- `ts/routes/pgrep-lab/+page.svelte` - interactive playground: 2D/3D toggle, live sliders for grid + height, auto-rotate, reset view, a live gap counter, and an editable panel for all nine units (Performance + Coverage sliders, leading-score M/P/R picker). One reactive `surface = buildSurface(units)` drives both renderers. The four isolation tiles remain below as documentation.
- `ts/routes/pgrep-lab/+layout.ts` - added `ssr = false` / `prerender = false` (WebGL is client-only).
- Verified live (Vite dev, light + dark): 3D renders with score hues + floor glow, filling a unit's coverage closes its hole and drops the gap count, height/grid reshape live, 2D fallback shows the same surface with labels, auto-rotate orbits.
- Three.js resolves `three/addons/controls/OrbitControls.js` via its `exports` map (checked in node_modules). `three` is MIT.
- Dev note: Chromium restores `<input type=range>` values across Vite HMR reloads and fires spurious `input` events; harmless dev-only noise, does not happen in the Anki webview.

## Progress

- [x] Design system in the repo (tokens + fonts + deps)
- [x] Core components (ScoreCard, Manifold) + renderer + `buildSurface`
- [x] Home surface, verified live (light + dark)
- [x] Manifold lab, proves data-driven
- [x] Manifold 3D (Three.js) renderer + component + interactive lab, verified live
- [ ] Reconcile Home + layout with your committed shell (bridge, `+layout.ts`)
- [ ] Wire Home to real data via `pgrepCall`
- [ ] Remaining components (StudyFrame, ChoiceList, HintRung, GradeBar, CoverageBar, ReliabilityDiagram)
- [ ] Remaining surfaces (Study, Progress, Cards, Library, Exam, Settings, Diagnostic, mobile)
- [ ] Preserve the UI work in a commit (currently staged, at risk of a hard reset)

_Sources: `ux-foundation.md`; the committed pgrep shell (`bridge.ts`, `+layout.ts`); direct reads of the fork; this session's build and verification._
