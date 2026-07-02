# pgrep Frontend Execution Guide (Part D, step by step)

**Purpose:** turn the Claude Design work into shipped Svelte in the repo, one small step at a time. This is the executable version of Part D in `claude-design-prompts.md`, and it is the frontend half of build layer **L2** in `build-plan.md`.

## How we work together

- **I drive:** terminal commands, file edits, and the delegation prompts for Claude Code or subagents.
- **You drive:** the Claude Design canvas (Parts A, B, C, C12) and the yes/no approvals between steps.
- **One step at a time.** Every step has a clear done-check. We do not start the next step until the current one is green.
- **Mock first.** We build the UI against fake data so the frontend can proceed before the Rust engine work (L1) is finished. Real backend wiring is the last step.

## Where this sits in the build plan

- **L0 (must be true first):** the fork builds and runs (`just run`). This guide assumes L0 is green.
- **L1 (needed only for Step 6):** the Rust selector plus the Problem and Attempt notetypes and their RPCs. Until then we use mock data.
- **This guide = L2 frontend:** land the design system, build the components, build the surfaces, then wire them.

## Honest caveat

Claude Design and its Claude Code handoff bias React and Tailwind. pgrep is Svelte 5 plus SCSS. So the tokens and the component spec transfer, the framework does not. We use Claude Design as the source of truth for the look, and implement Svelte deliberately in `ts/`.

---

## Progress checklist

- [x] Step 0. Confirm the fork builds (L0 gate) - done, prior build present (out/ 9.9G, toolchain ready)
- [x] Step 1. Isolate the work on a branch - done, on branch pgrep-ui-design
- [x] Step 2. Land dependencies and design tokens - deps installed (three, lucide-static, inter, jetbrains-mono, @types/three); tokens ported to ts/lib/sass/_pgrep.scss (scoped .pgrep, matches export exactly); fonts import wired at the first pgrep page. NOTE: run `just fix-minilints` at commit time (it needs staged changes) to record the new package licenses before `just check`
- [ ] Step 3. Establish the design system in Claude Design and export
- [~] Step 4. Build the component library in Svelte (mock data) - done so far: ScoreCard.svelte, Manifold.svelte + ts/lib/pgrep/manifold.ts (renderer ported from the export), tokens/fonts, all verified live. Remaining: StudyFrame, ChoiceList, HintRung, GradeBar, CoverageBar, ReliabilityDiagram
- [~] Step 5. Build the surfaces one at a time (mock data) - Home DONE and verified LIVE in Anki in light and dark (manifold redraws on theme flip). Remaining: Study (commit + ladder), Progress, Cards, Library, Exam, Settings, Diagnostic, mobile
- [ ] Step 6. Wire the surfaces to the engine (needs L1)
- [ ] Step 7. Verify and finish

---

## Step 0. Confirm the fork builds (L0 gate)

**Goal:** make sure the toolchain is set up and the app runs, so later verification works.
**I run:**

```bash
# from the repo root
just run
```

**Done-check:** Anki launches, and `out/extracted/node/bin/yarn` exists (the vendored yarn we use later).
**If it does not build:** that is an L0 problem, not a design problem. See `build-plan.md` L0.

---

## Step 1. Isolate the work on a branch

**Goal:** keep this off `main`.
**I run:**

```bash
git checkout -b pgrep-ui
```

**Done-check:** `git status` shows the new branch.

---

## Step 2. Land dependencies and design tokens (the durable design system)

**Goal:** get the fonts, icons, 3D lib, and the pgrep color and type tokens into the repo. This is the highest-value step because it is the system, not a screen.

**I run (dependencies):**

```bash
out/extracted/node/bin/yarn add three lucide-static @fontsource-variable/inter @fontsource-variable/jetbrains-mono
out/extracted/node/bin/yarn add -D @types/three
```

**I edit (tokens):**
- Add pgrep tokens to `ts/lib/sass/_vars.scss` (the `$vars` map that `_root-vars.scss` turns into CSS variables): warm canvas, surface, elevated, border, text, and muted neutrals for light and dark, plus the amber, blue, and lilac data colors with their on-light variants, plus `--font-ui` and `--font-mono`.
- Import Inter and JetBrains Mono (Fontsource) so the tokens resolve.
- Light and dark ride the existing `.night-mode` class.

**I run (verify):**

```bash
just fix-minilints   # refresh ts/licenses.json for the new packages
just lint            # check:svelte, check:typescript, check:eslint
```

**Done-check:** `just lint` passes, and the new CSS variables exist in the built output.

---

## Step 3. Establish the design system in Claude Design and export

**You do (this one is yours):**
1. In Claude Design, point it at this repo's `ts/` folder and `ux-foundation.md`, and attach the PNGs in `../../assets/ux/`.
2. Run Part A (design system), Part B (components), Part C (screens), then C12 (light pass) from `claude-design-prompts.md`.
3. Export with Send to Claude Code to get the handoff bundle.

**Done-check:** you have a saved design system and an exported bundle. Tell me when this is done and I will use it as the visual spec for the next steps.

---

## Step 4. Build the component library in Svelte (mock data)

**Goal:** the reusable primitives, rendered against fake data, before any backend.
**I do or dispatch a subagent with this prompt:**

```text
Build the pgrep component primitives as Svelte 5 components in ts/lib (or ts/lib/pgrep). Follow the existing conventions in ts/lib/components (look at Container.svelte, Col.svelte, Button). Style only with the CSS variables added in ts/lib/sass (no hardcoded colors). Components: ScoreCard (with abstain state), StudyFrame, ChoiceList (default, selected, committed), HintRung (with hint budget), CoverageBar, ReliabilityDiagram, Manifold (Three.js surface with a 2D D3 contour fallback). Icons come from ts/lib/components/icons.ts (add Lucide via the .svg?component pattern). Equations use MathJax. Charts use D3, reusing helpers in ts/routes/graphs. Render each with mock props on a scratch page so they can be seen. Match the Claude Design components and the reference PNGs in docs_pgrep/assets/ux. Use Context7 for Three.js, D3, and Svelte 5 APIs. Run just lint until clean.
```

**Done-check:** the components render with mock data (via `just web-watch`) and `just lint` passes.

---

## Step 5. Build the surfaces one at a time (mock data)

**Goal:** one route per surface, composed from the components, still on mock data. Order: Home, then Study, then Progress, then the rest.
**Pattern (copy `ts/routes/congrats`):** a folder under `ts/routes/<surface>/` with `+page.ts` (a `load` that returns mock data for now), `+page.svelte` (composes the components), and `lib.ts`.
**I do or dispatch a subagent, per surface, with this prompt (swap the surface):**

```text
Build the pgrep <SURFACE> surface as a SvelteKit route under ts/routes/<surface>, copying the structure of ts/routes/congrats (+page.ts load, +page.svelte, lib.ts). For now the load returns mock data (no backend). Compose the surface from the pgrep components in ts/lib. Match the Claude Design mockup and the reference PNG. Serve it via just web-watch and confirm it renders at /_anki/pages. Keep all copy free of em-dashes and heavy colons. Run just lint until clean.
```

**Done-check:** the surface renders at `http://localhost:40000/_anki/pages/<surface>.html`.

---

## Step 6. Wire the surfaces to the engine (needs L1)

**Goal:** replace mock data with real engine calls.
**Depends on L1** (`build-plan.md`): the points-at-stake selector plus the Problem and Attempt notetypes and their RPCs.
**Steps:** add the proto messages in `proto/anki/*.proto`, implement them on `Collection` in Rust (`impl ...Service`), run `just check` to regenerate the TypeScript and Python bridges, then swap each `+page.ts` mock for the real call from `@generated/backend` (the same way `ts/routes/congrats/+page.ts` calls `congratsInfo`).
**Done-check:** each surface shows real data, `just check` passes, undo and sync still work.

---

## Step 7. Verify and finish

**I run:**

```bash
just check   # format, build, all checks
```

**Then:** commit, and if you want, open a PR. This closes the frontend half of L2.

---

_Sources: `claude-design-prompts.md` (Part D), `build-plan.md` (L0, L1, L2), `ux-foundation.md` (tokens, components, stack), and direct reads of the fork (`ts/routes/congrats`, `ts/lib/sass`, `ts/lib/components/icons.ts`, `qt/aqt/mediasrv.py`)._
