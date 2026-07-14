# Card Sets Library ("the wheel") + calibration gate, plan

Date: 2026-07-06. Status: approved for planning. Author: pair session.

This plan integrates the `design/claude-design/design_handoff_card_sets/` handoff
(a 3D "wheel" browser for flash card sets) into the pgrep Svelte/TS frontend, and
wires it to a first-run **calibration gate** so the generation-effect authoring
becomes the learning-science pillar of onboarding. It is written to survive a
chat compaction: every decision, mapping, and phase is captured here.

---

## 1. Locked decisions

These were settled in the design session. Do not relitigate without the owner.

1. **Placement.** The wheel becomes the **Library** surface. `/pgrep/library`
   renders one of two states depending on calibration status (see §3).
2. **A "set" = one of the 9 blueprint categories** (Mechanics, E&M, Quantum,
   Thermo/Stat Mech, Optics & Waves, Atomic, Special Relativity, Lab Methods,
   Specialized). The wheel handles any N; the handoff's fixture used 8, we use 9.
3. **"Add a card"** (per set, on the wheel) authors the card **as-is** into that
   set's category (front + back), **no AI**. It is separate from calibration.
4. **Calibration** is the guided, generation-effect authoring (write one card in
   your own words per area). It is the learning-science pillar and, with AI on,
   also seeds **stylize**/**gap-fill**.
5. **Calibration is required only when AI is on.** Turning AI on is the trigger.
   - AI **off** → Study is open, Library is the wheel immediately, calibration is
     **not required** (offered as an optional/recommended entry, never a wall).
   - AI **on** → **Study is gated** behind calibration; Library opens to the
     walkthrough until calibration is complete, then becomes the wheel.
6. **First-run defaults.** A new collection starts with **AI on**. The onboarding
   sequence is: **welcome → required Diagnostic → Study gated by calibration**
   (because AI is on). The escape hatch (Settings → turn AI off → study without
   calibrating) exists but is **not advertised** in the onboarding copy.
7. **Required calibration coverage: one card per blueprint category (9)**, so the
   gate and the wheel's sets line up. (Today's walkthrough steps through 20
   subtopics; we align it to the 9 categories. Switching back to 20 is a one-line
   change to the required set if the owner prefers.)
8. **Fidelity.** The wheel is high-fidelity: recreate the geometry math, spring,
   FLIP deal, and timings from `TECHNICAL-SPEC.md` exactly. Recreate in Svelte,
   inside the app's existing rail shell, using pgrep tokens and `renderMath`.

## 2. Context

pgrep is a Physics-GRE study app forked from Anki: a Svelte/TS web frontend
(`ts/routes/pgrep/**`, `ts/lib/components/**`) served through Qt, a Python/Rust
engine (`pylib/anki/pgrep/**`), and a JSON bridge (`qt/aqt/pgrep.py`, camelCased
mediasrv POST handlers registered in `pgrep_post_handlers`). The rail
(`ts/lib/components/NavRail.svelte`) already exposes Home / Study / Progress /
Library / Settings, so the handoff's "App rail" variant is our real shell (drop
its "Immersive" variant). Cards are `Basic` notes tagged `topic::<category>[::<sub>]`
across `PGRE::Sample` (seeded) and `PGRE::Generated` (authored + AI). A first-run
**Diagnostic** gate already exists (`pgrep_diagnostic_status`, stored in the
collection config), which the calibration gate mirrors.

Handoff source of truth (keep in the repo, reference it, do not duplicate the
tuned constants):

- `design/claude-design/design_handoff_card_sets/TECHNICAL-SPEC.md` — geometry
  math (§3), feel presets (§4), inputs (§5), stack (§6), FLIP open/close (§7),
  grid + composer (§8), tokens (§9), a11y (§10).
- `design/claude-design/design_handoff_card_sets/Card Sets.dc.html` — dark
  reference markup + the `DCLogic` component (state, rAF `tick`, `flyIn`, `close`,
  `renderVals`). This is the behavior to port.
- `PHILOSOPHY.md` — the reasoning (attention gradient, circular queue, shuffle
  not slide, literal dealing).

## 3. The Library: two states

`/pgrep/library` renders exactly one of:

- **Calibration walkthrough** (pre-calibration, AI on) — today's guided authoring
  flow, essentially as-is (the current `library/+page.svelte`), condensed to one
  card per category (§1.7). This is the generation-effect act.
- **The wheel** (calibrated, or AI off) — the Card Sets browser (§5).

Selection rule (client reads calibration + AI status on mount):

```
show = (aiEnabled && !calibrated) ? "walkthrough" : "wheel"
```

For **AI-off, uncalibrated** users the wheel shows immediately, with a dismissible
"Teach pgrep your style" entry that launches the walkthrough voluntarily.

## 4. The calibration gate

- **Status**, mirroring the Diagnostic gate: a collection-config flag, read via a
  new `pgrep_calibration_status` handler → `{ calibrated: bool, authored: int,
  required: int }`. `calibrated` is true once the learner has authored one card
  in each of the 9 categories (or an explicit "complete" is recorded).
- **Marking complete.** Authoring through the walkthrough uses the existing
  `author_seed` path (`generation.author_seed`, already wired via
  `pgrepLibraryGenerate`). On each authored card, recompute coverage; when all 9
  categories have ≥1 authored card, set the calibrated flag. (Add a small
  `anki.pgrep.calibration` module: `calibration_status(col)` + the coverage
  computation over authored/seed-tagged notes by category.)
- **Study lock.** `ts/routes/pgrep/study/+page.svelte` reads
  `{ aiEnabled, calibrated }` on mount. When `aiEnabled && !calibrated`, the
  launcher renders a calm locked state: "Calibrate first — writing your own cards
  is how this sticks," with a primary button to `/pgrep/library`. Home and
  Progress stay open. When not gated, Study behaves as today.
- **AI toggle is the trigger.** `settings.set_ai_enabled` already exists
  (`pgrepAiSetEnabled`). No backend change needed for the rule; the gate is
  derived (`aiEnabled && !calibrated`) wherever it is read. Turning AI on while
  uncalibrated makes the next Study visit show the lock and the Library show the
  walkthrough; turning AI off relaxes both.
- **First-run AI default.** New collections start AI-on. Set the default in
  `anki.pgrep.ai_config` (today AI is off by default) so onboarding realizes the
  "calibration is paramount" path by default, with the unadvertised off switch.

## 5. The wheel (Card Sets browser)

### 5.1 Data

New read model + handler:

- `anki.pgrep.card_sets.list_card_sets(col) -> list[dict]`, one entry per
  blueprint category that has any cards:

```json
{
  "category": "mechanics",
  "name": "Classical Mechanics",
  "cards": [ { "note_id": 123, "front": "…(TeX allowed)…", "back": "…" }, … ]
}
```

Enumerate `Basic` notes tagged `topic::<category>*` across `PGRE::Sample` +
`PGRE::Generated`; group by `category_for(tags)` (see `anki.pgrep.tags`); order
categories in blueprint order (`CATEGORY_SLUGS`). Counts and the face preview
(`cards[0].front`) are real — no invented numbers (honesty rule).

- Bridge: `pgrep_card_sets` in `qt/aqt/pgrep.py`, registered in
  `pgrep_post_handlers`. Reachable as `pgrepCardSets`.

### 5.2 Component port (React `DCLogic` → Svelte 5)

Create `ts/lib/components/CardWheel.svelte` (browse) and either fold the opened
grid into it or a sibling `ts/lib/components/CardSetGrid.svelte`. Port faithfully:

- **State** (`TECHNICAL-SPEC.md` §2): `T` (target, float, wraps mod N), `A`
  (animated, spring), `spread` (0.04→1 intro), `sel = round(T) mod N`, `hovered`,
  `open`, `closing`, `adding`, `dragging`.
- **Per-frame rAF loop** (§3): compute `off/phi/d/dx/dz/rot/opacity/zIndex` per
  deck and write styles directly on bound deck nodes (`bind:this` into an array).
  Spring: `A += (T-A) * (dragging?0.40:0.16)`; `spread += (1-spread)*0.09`. Do
  **not** put CSS transitions on the deck wrapper — the spring is the animation.
- **Feel presets** (§4): `Ferris` (default), `Shallow`, `Deep`. Keep as a const
  map; default Ferris. Expose as a prop for the dev gallery only.
- **Inputs → all write `T`** (§5): wheel (`+= (dY+dX)*0.0032`, `preventDefault`,
  non-passive, snap `round(T)` 150ms after last event); drag (`T0 - dx/pxPerIndex`,
  `pxPerIndex = R*sp(rad)`, >6px suppresses the click); arrows (`round(T)±1`);
  Enter/Space opens `sel`; dot + side-deck clicks use shortest path
  (`round(T)+wrapOff(i-sel)`). No clamping; `wrap()` handles display.
- **Stack** (§6): 4 layers 300×380, r16; back cards `translateY(-5k) translateZ(-k)`,
  hover (centered only) `-12/-23/-34`; front card carries the only elevated shadow.
- **Open/close FLIP** (§7): on open, mount grid, fade wheel to opacity 0 / scale
  .965 (360ms); measure each grid cell, set `translate(deckCenter-cardCenter)
  rotate(scatter) scale(.82) opacity 0`, reflow, release to identity with
  `transform 460ms --ease-spring` + `opacity 300ms`, delay `16ms*i` (+40ms
  opacity). Scatter `((i*37)%9-4)*1.6`. Close reverses, delay `10ms*(n-1-i)`,
  420ms, then unmount; guard timeout `≈420+10(n-1)+100`ms. Esc order: composer →
  close composer; else grid → close.
- **Grid + composer** (§8): 4-col grid, 14px gap, max-width 1240; card 14px,
  min-height 136; dashed "Add a card" tile → inline front/back composer
  (author-as-is, §6 below). Chrome: "All sets" back pill, title + real count,
  "Study this set".
- **Math**: use `renderMath` from `$lib/pgrep/math` on card fronts; re-typeset
  after opening a set and after adding a card. Not the CDN MathJax.

### 5.3 Actions

- **Study this set** → navigate to `/pgrep/study?topic=<category_slug>` (the
  focus-drill deep link already handled in `study/+page.svelte` `onMount`).
- **Add a card** → `pgrepAddCard` (new handler) → `generation.author_seed(col,
  front, back, topic="topic::<category>")`, no AI; then reload the set's cards and
  re-typeset. Empty front → refocus, no submit (matches the reference).

### 5.4 Tokens (design §9 → pgrep)

Map to existing tokens so light/dark come for free; reconcile the two extra shades
rather than hardcoding hex:

| design                       | pgrep token                                         | note                            |
| ---------------------------- | --------------------------------------------------- | ------------------------------- |
| `--bg`                       | `--canvas`                                          | frame background                |
| `--card`                     | `--surface`                                         | front card, grid card           |
| `--card-back` / `--bg-inset` | `--elevated`                                        | back cards, composer inputs     |
| `--border` / `--border-back` | `--border`                                          | hairlines                       |
| `--border-strong` (hover)    | `--muted`                                           | matches CardFace hover          |
| `--faint` (counts)           | `--muted`                                           | mono count text                 |
| `--muted`                    | `--muted`                                           | labels                          |
| `--text`                     | `--text`                                            | headings, front text            |
| shadows                      | `--shadow-card`                                     | only the front card is elevated |
| easing/time                  | `--ease-spring` + literal durations (280/360/460ms) |                                 |

Type: `--font-ui` (Inter) for UI, `--font-mono` (JetBrains Mono, `tnum lnum`) for
counts. Radii via existing `--radius-*` (grid 14 / deck 16 / dots 999).

### 5.5 pgrep additions the handoff omits

- **Reduced motion** (`prefers-reduced-motion: reduce`): snap `A=T` and
  `spread=1` instantly; skip the FLIP (cards appear in place, wheel cross-fade
  becomes instant). Follow the pattern already used across pgrep components.
- **Performance**: stop the rAF loop when settled (`|T-A|<1e-3`, `spread>0.999`,
  not dragging, not mid open/close) and restart it on any input, hover, or
  open/close. The prototype loops forever; the app must idle.
- **Responsive/mobile** (Phase 4): the handoff is a fixed 1440×900 desktop frame,
  and the app has a phone rail-drawer. Provide a small-screen story: scale the
  stage down and, below a breakpoint, fall back to a plain vertical list of sets
  (each row = name, count, preview, open) so the surface stays usable on a phone.
- **Empty states**: a set with 0 cards, and the "no sets seeded" case (ties into
  the existing `pgrepRestartCards` refill). The wheel must render a calm empty
  state, not a broken carousel.
- **Accessibility** (§10): decks `role="button"` + `aria-label="{name}, {n} cards"`;
  dots `aria-label="Go to {name}"`; keyboard per §5; the wheel layer keeps
  `pointer-events:none` while a set is open.

## 6. The onboarding flow (first run)

1. New collection → **AI on** by default (§4).
2. **Welcome screen** → short intro, single "Get started" action. (Confirm
   whether one exists; if not, add a minimal one. It is not the calibration.)
3. **Diagnostic** (required, exists) → places the learner across topics.
4. Learner lands in the app. **Study is gated** (AI on, not yet calibrated):
   the launcher shows the "Calibrate first" lock → Library.
5. **Library** shows the calibration walkthrough (one card per category). On
   completion the flag flips; Library becomes the wheel and Study unlocks.
6. **Unadvertised escape hatch**: Settings → turn AI off → gate relaxes,
   learner can study the provided material without calibrating. Onboarding copy
   never points at this.

## 7. Phasing / workstreams

Each phase is independently shippable and reviewable. Build on a dedicated
worktree off `main` (`feat/card-sets-wheel`), per repo worktree rules. Run
`just check` before marking a phase done; add a dev-gallery fixture for visual
review (per the gallery workflow).

### Phase 1 — The wheel browser (read-only)

**Backend**

- Create `pylib/anki/pgrep/card_sets.py` → `list_card_sets(col)` (§5.1).
- Add `pgrep_card_sets` to `qt/aqt/pgrep.py` + register in `pgrep_post_handlers`.
- Test `pylib/tests/test_pgrep_card_sets.py`: seeded collection groups into
  blueprint-ordered categories; real counts; face preview = first front; empty
  collection → empty list; generated cards included.

**Frontend**

- Create `ts/lib/components/CardWheel.svelte` (stage + decks + dots + open grid),
  ported per §5.2, with reduced-motion + settle-and-stop rAF from the start.
- `ts/routes/pgrep/library/+page.svelte` renders the wheel (calibrated/AI-off
  path) fed by `pgrepCardSets`; open → grid → "Study this set" → study deep link.
  (Two-state switch lands in Phase 3; for now render the wheel.)
- Dev gallery fixture `ts/routes/pgrep-lab/card-sets/+page.svelte` with fixture
  data + the `wheelFeel` prop, both themes, so reviewers can inspect motion.

**Acceptance:** the wheel browses the real 9 category sets, snaps centered, opens
a set into the dealt grid, "Study this set" enters that topic's Study; motion
matches the reference; reduced-motion snaps; the loop idles when settled; light +
dark correct.

### Phase 2 — Add a card

- `pgrep_add_card` handler → `generation.author_seed` (no AI); register it.
- Wire the composer (§5.3): dashed tile → inline front/back → submit appends and
  re-typesets; empty front refocuses. Counts and the face update reactively.
- Test: `pgrep_add_card` adds a `Basic` note with the category topic tag to
  `PGRE::Generated`, no AI modules imported.

**Acceptance:** adding a card in a set persists it, updates the count and (if it
becomes the new first card) the face; no AI is invoked.

### Phase 3 — Calibration gate + Library layering + Study lock

- Create `anki.pgrep.calibration`: `calibration_status(col)` (authored coverage
  by category, `calibrated` flag) + set-on-completion; `pgrep_calibration_status`
  handler + register.
- Flip AI default to on for new collections (`ai_config`).
- `library/+page.svelte`: two-state switch (§3) — walkthrough (existing flow,
  condensed to 9 categories) when `aiEnabled && !calibrated`, else the wheel;
  AI-off adds the optional "Teach pgrep your style" entry. Mark calibrated when
  coverage completes.
- `study/+page.svelte`: the "Calibrate first" lock when `aiEnabled && !calibrated`.
- Onboarding: welcome screen (if missing) + ensure Diagnostic-then-calibration
  order; verify the Settings AI toggle relaxes/tightens the gate live.
- Tests: `calibration_status` coverage math; study gate logic (unit where
  possible); an e2e (`ts/tests/e2e/`) for the first-run gate if feasible.

**Acceptance:** a fresh collection (AI on) is forced through Diagnostic, then
Study is locked until the 9-category calibration completes, after which Library
becomes the wheel and Study unlocks; turning AI off in Settings removes the gate.

### Phase 4 — Responsive / mobile + polish

- Small-screen fallback (§5.5): scaled stage, then a vertical list below a
  breakpoint; phone-drawer rail interplay.
- Final motion/token QA in both themes; a11y pass (keyboard, labels, focus).
- Empty-set and no-sets states.

**Acceptance:** usable on a phone width; keyboard-navigable; empty states calm;
`just check` green.

## 8. Data contracts (summary)

- `pgrepCardSets {} -> [{ category, name, cards: [{ note_id, front, back }] }]`
- `pgrepAddCard { category, front, back } -> { note_id, category }`
- `pgrepCalibrationStatus {} -> { calibrated, authored, required }`
- Existing, reused: `pgrepAiStatus`, `pgrepAiSetEnabled`, `pgrepStudyStart`
  (`?topic=` deep link), `pgrepLibraryGenerate` (walkthrough authoring),
  `pgrepDiagnosticStatus`, `pgrepRestartCards`.

## 9. Risks / open items

- **Perf of the rAF + perspective** with 9 decks: fine, but the settle-and-stop
  is required so it doesn't burn CPU idling.
- **Calibration coverage granularity** (9 vs 20): locked to 9 (§1.7); revisit
  only if onboarding feels too thin.
- **Welcome screen existence**: confirm during Phase 3; add a minimal one if
  absent.
- **AI-on-by-default** is a genuine product change (today off); it is what makes
  calibration effectively required. The unadvertised off-switch is the pressure
  valve.
- **Honesty rule**: every count/preview on the wheel is real; keep it that way.

## 10. References

- Handoff: `design/claude-design/design_handoff_card_sets/` (README, PHILOSOPHY,
  TECHNICAL-SPEC, `Card Sets.dc.html`, `Card Sets Light.dc.html`).
- Existing patterns: `ts/lib/components/{CardFace,StudyFrame,NavRail}.svelte`,
  `ts/routes/pgrep/{library,study,settings,diagnostic}/+page.svelte`,
  `pylib/anki/pgrep/{generation,seed,tags,ai_config,diagnostic,settings}.py`,
  `qt/aqt/pgrep.py`, `ts/lib/sass/_pgrep.scss` (tokens).
