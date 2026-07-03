# pgrep claude.design Prompts and Repo Handoff

Full rationale for every choice lives in `ux-foundation.md`.

## How Claude Design actually wants to be used

Claude Design is not a page generator. It works in this order, and so should we:

1. **Establish a design system** once. During onboarding it reads a codebase and design files and builds a token set plus components, then applies that system to every later project. We seed it with Part A below (and by pointing it at this repo).
2. **Build a component library** from that system (Part B). These primitives get reused across every screen, so the screens stay consistent instead of each being a one-off.
3. **Compose screens** from those components (Part C). This is what my first draft had, and only that. The screens are the last step, not the first.
4. **Hand off to the repo** (Part D). This is the part that turns pictures into shipped Svelte.

Honest note on the stack: Claude Design and its Claude Code handoff default to React and Tailwind. pgrep is **Svelte 5 + SCSS variables + Vite** (see `ux-foundation.md` section 10). So use Claude Design to lock the visuals and tokens, and treat the handoff as a spec that Claude Code implements as Svelte inside `ts/`, not as a drop-in React app. Part D covers exactly that.

---

# Part A. Establish the design system (do this first)

**Step 1, onboarding.** In Claude Design, point it at this repo's `ts/` folder and at `ux-foundation.md`, and attach the reference PNGs in `assets/ux/`. This lets it read the real SCSS tokens, the icon module, and the intended look.

**Step 2, define and save the system.** Paste this and ask Claude Design to save it as the reusable design system for the workspace.

```text
Create and save this as the pgrep design system, to apply to every project in this workspace.

Product: pgrep, a Physics GRE study app built on the Anki engine. Personality: an honest measuring instrument that renders physics beautifully. Element craft like Claude, Linear, and Apple. Calm, precise, content first, nothing decorative.

Theme: adaptive. Light and dark are both first class and both must be beautiful. Default mockups to dark.

Color tokens, with reserved meanings (never use these hues for decoration):
- canvas: light #FBFAF8, dark #262624 (warm grey, not black)
- surface: light #FFFFFF, dark #302F2C
- elevated: light #F5F2EC, dark #3A3835
- border: light #E8E4DA, dark #45433E
- text: light #262624, dark #ECEAE3
- muted: light #6E6B64, dark #A5A199
- memory (amber): fill #EBCB8B, text-on-light #A9752A
- performance (blue): fill #81A1C1, text-on-light #5E81AC
- readiness (lilac): fill #C4A7D6, text-on-light #7E6593
- primary action: monochrome, near-black #262624 on light and near-white #ECEAE3 on dark
- states: success #A3BE8C, caution #D08770, error #BF616A

Type: Inter for UI with tabular lining figures for all numbers, JetBrains Mono for timers and dense data, MathJax for equations.

Shape and motion: squircle cards, hairline borders, soft shadows, 8pt grid, generous whitespace, calm spring motion 200 to 300ms.

Copy rules (strict): no em-dashes, no colon-heavy phrasing, short labels. Voice honest and lightly human. Never flatter a right answer, never punish a wrong one.

Honesty rule baked into components: any score shows a point number, a likely range, a how sure read, and last updated. When data is thin it abstains and says what is missing.

Build target: production is Svelte 5 with SCSS variable theming, not React or Tailwind. Keep components framework-neutral and token-driven so they map onto that.
```

---

# Part B. Component library (build the system pieces)

Generate this as a single components canvas. These primitives are reused by every screen.

```text
Design a component library sheet for the pgrep design system, dark mode, using the saved tokens. Lay the components out on one canvas with labels, and show the key states of each.

1. Buttons: primary (monochrome), secondary (outline), ghost, and destructive. Show default, hover, focus ring, and disabled.
2. Inputs: text input, textarea with a character counter, segmented control, toggle. Show focus and error.
3. Topic chip: a small pill, for example Mechanics, in neutral and in each data color.
4. Navigation: a desktop left rail (Home, Study, Progress, Library, Settings) with a nested-contour-loop logo and a streak indicator, and a mobile bottom tab bar (Home, Study, Progress).
5. Score card: title, large tabular number, a likely range like 64 to 74, a how sure read, last updated, and a tiny sparkline. Provide three color variants (Memory amber, Performance blue, Readiness lilac) and an abstain state reading Not enough evidence yet with a link See what is missing.
6. Study card frame: minimal top chrome with a small progress like 7 of 20, a topic chip, and a close icon.
7. MCQ choice list: five choices A to E in three states, default, selected (thin outline in the domain color), and committed.
8. Hint rung: a calm card with a title, a hint budget of three dots, a sub-goal question, a textarea, and a secondary Show the step button. Never reveals the final answer.
9. Coverage bar: a horizontal bar segmented by topic with a percent and an abstain note.
10. Reliability diagram: a small chart, predicted probability on x, observed accuracy on y, dashed diagonal reference, a data curve, a Brier figure, and a plain-language read.
11. Manifold: a clean 3D wireframe surface plot (height is performance, glow is memory, holes are gaps) and its 2D top-down contour fallback shown beside it.

Everything monochrome for interaction, amber and blue and lilac reserved for data. No em-dashes.
```

---

# Part C. Screens (compose from the components)

Each screen should reuse the Part B components. Prompt 0 (Part A) must be established first.

## C1. Home (Readiness), desktop, dark

```text
Design the Home screen for pgrep, desktop, dark mode, using the saved components.

Layout: the left rail, a large hero in the center, a right column of three score cards.

Hero: the wireframe manifold (height is performance, glow is memory, holes are gaps), with a few small topic labels on thin leader lines such as Mechanics, E and M, Quantum. It reads as an instrument, not photoreal terrain.

Right column: three score cards, Memory amber, Performance blue, Readiness lilac, each with a number, a likely range like 64 to 74, a how sure read, and Updated 2h ago. Show Readiness in the abstain state, Not enough evidence yet, with a link See what is missing.

Below the hero: one wide Today card, a single recommended next action with an estimated time and an impact tag, and a monochrome primary button Start session. A small streak in the rail.
```

## C2. Study, solve a problem, desktop, dark (two states)

```text
Design the Study problem view for pgrep, desktop, dark mode, using the study card frame and MCQ choice list. Generate two states.

State A, commit: a physics multiple choice problem stated in words with a MathJax equation where needed, five choices A to E with one selected in a thin blue outline, a monochrome primary button Commit, and a muted line Help unlocks after you commit. No confidence control. Do not reveal the answer above the choices.

State B, wrong-answer ladder: the committed wrong answer shown de-emphasized with a small tag Your answer, not correct. A hint rung titled Break it down, budget 1 of 3 hints, Step 1 of 3, a sub-goal question such as Which conservation law applies here, and why, a textarea, and a secondary Show the step button that reveals the stored sub-goal for self comparison. Never show the final answer. Footer Working it out yourself is the point. Blue accent, not a red error state.
```

## C3. Cards door, review, light

```text
Design the flashcard review for pgrep, light mode, amber accent (the memory door), using the study card frame.

A focused single column. Top shows small progress like 12 of 30 and a topic chip Electromagnetism. Center: a large flashcard in the revealed state, a concept prompt with a MathJax equation, a thin divider, then the answer with a short symbol legend. Bottom: four grade buttons Again, Hard, Good, Easy.
```

## C4. Progress, desktop, dark

```text
Design the Progress screen for pgrep, desktop, dark mode, the honest evidence dashboard, using the left rail (Home, Study, Progress, Library, Settings).

Top: a Coverage card, a large percent, a bar segmented by topic, and a note Coverage is below 80 percent, so score predictions abstain for now.

Below: two calibration cards, Memory calibration (amber) and Performance calibration (blue), each a reliability diagram with a dashed diagonal, a data curve, a Brier figure, and a read like Underconfident or Well calibrated.
```

## C5. Library, author a seed, desktop, dark

```text
Design the Library authoring screen for pgrep, desktop, dark mode, amber accent, using the left rail.

Heading Author a seed. A guiding line Write one card in your own words. We scale the rest in your style. Left: an editor card with Front and Back fields holding a conceptual physics card, topic chip Quantum Mechanics. Right: a panel AI conformed siblings listing three generated cards in the same style, each with a source citation such as Griffiths QM ch.2 and a status tag, two Verified and one Needs review. Footer chip Gold set gate passed.
```

## C6. Exam mode, desktop, dark

```text
Design Exam mode for pgrep, desktop, dark mode, focused and distraction free, strictly monochrome buttons.

Top center: a large countdown timer in JetBrains Mono like 1:42:09 with a small progress like 23 / 70. Center: a physics multiple choice question stated in words, five choices A to E, none selected, and the correct answer must be one of the five and must not be shown above the choices. Bottom: Previous, Next, and a Flag toggle, all monochrome. A muted line No hints in exam mode. Timed, real proportions. A slim question navigator strip of numbered squares along the bottom, several filled.
```

## C7. Mobile companion, dark (two phones)

```text
Design the pgrep phone companion, dark mode, iOS-like, two phones side by side, monochrome primary buttons.

Left phone Home: a heading Home and a line Your readiness at a glance, a small wireframe manifold thumbnail, three compact score rows Memory amber, Performance blue, Readiness lilac each with a number and a range like 70 to 90, a monochrome Start session button, and a bottom tab bar Home, Study, Progress.

Right phone session: a physics multiple choice question with a MathJax equation and choices A to E with one selected in a blue outline, and a monochrome Commit button. No confidence control, no answer shown above the choices.
```

## C8. Diagnostic (first run), desktop, dark

```text
Design the Diagnostic placement flow for pgrep, desktop, dark mode.

A calm centered card. A short heading Let us place your topics and a line This takes a few minutes and seeds your map. One physics question at a time with choices A to E and a subtle progress like 4 of 12. No hints, no scores yet. On completion, a summary that places each topic as strong or rusty on a compact topic list or a small manifold preview, and a monochrome primary button See your map.
```

## C9. Settings, desktop, dark

```text
Design the Settings screen for pgrep, desktop, dark mode, using the left rail.

Grouped inset rows. Group Study: target retention slider, test date picker. Group AI: an AI on and off toggle with a note The app always works and still scores with AI off. Group Sync: sync now, account. Group Appearance: light, dark, system. Group Data: export, reset. Clean, quiet, no colons in labels.
```

## C10. Session launcher and Focus drill, desktop, dark

```text
Design two Study entry views for pgrep, desktop, dark mode.

View A, session launcher: three large choices, Start today's session (recommended, interleaved, shows the planned mix of cards and problems), Focus drill (pick one topic), and Exam mode (timed mock). Each is a calm card with a one line description. Monochrome primary on the recommended one.

View B, focus drill picker: entered by tapping a topic on the manifold, or here. Show the selected topic, its due counts for cards and problems, and a monochrome Start button. If nothing is due, show a calm state offering ahead of schedule practice or generate.
```

## C11. States sheet (abstain, AI off, loading, empty) and light variants

```text
Design a states sheet for pgrep using the saved components.

1. Abstain: a Readiness score card that cannot speak yet, reading Not enough evidence yet, with what is missing and a link.
2. AI off: a hint rung and a Library panel in their AI-off form, using stored decompositions and reveal-and-self-compare, with a small AI off chip.
3. Loading: a score card and the manifold in a calm skeleton state.
4. Empty: a topic with no items, offering generate or practice.
Then render the Home screen and the Cards review in light mode to confirm the system is beautiful in both themes.
```

## C12. Full light-mode pass (everything)

```text
Produce the light mode version of the entire pgrep system, using the saved design system and its light tokens. Keep every layout, label, component, and state identical to the dark versions. Only the theme changes.

Light tokens to apply:
- canvas #FBFAF8 (warm off-white), surface #FFFFFF, elevated #F5F2EC
- hairline border #E8E4DA, kept visible but subtle
- text #262624, muted #6E6B64
- primary buttons stay monochrome, near-black #262624 fill with off-white text
- data colors use the darker on-light variants for text, strokes, and chart curves: Memory #A9752A, Performance #5E81AC, Readiness #7E6593. Use the pastel fills #EBCB8B, #81A1C1, #C4A7D6 only for small chips or fills, never as body text on white
- states success #A3BE8C, caution #D08770, error #BF616A

Light mode care:
- lean on soft shadows and hairline borders for depth, a warm paper feel like Claude and Apple light. No heavy shadows
- the manifold: a bare wireframe washes out on white, so place it in a subtly elevated panel and draw the surface in a darker ink with the amber to blue to lilac gradient, or use the 2D top-down contour map as the light hero. Keep holes and fog legible
- charts and reliability diagrams: subtle gridlines, curves in the darker data variants, diagonal reference in muted grey

Regenerate in light mode:
- the full component library: buttons, inputs, chips, nav rail and mobile tabs, score card and its abstain state, study card frame, MCQ choice list, hint rung, coverage bar, reliability diagram, and the manifold with its 2D contour
- every screen: Home, Study commit and ladder, Cards, Progress, Library, Exam, Mobile, Diagnostic, Settings, Session launcher and Focus drill, and the states sheet

Reserved meanings hold: amber Memory, blue Performance, lilac Readiness, monochrome for interaction. Copy rules hold: no em-dashes, no colon-heavy phrasing, short labels.
```

---

# Part D. Handoff to the repo (Claude Design to shipped Svelte)

The goal is durable design tokens and Svelte components in `ts/`, wired to the engine. This maps onto build layer **L2** in `build-plan.md`.

**1. Export the handoff bundle.** In Claude Design, use Send to Claude Code. The bundle carries the component spec, the tokens actually used, the layout hierarchy, and assets. It is a spec, not a PNG.

**2. Point Claude Code at the repo and steer it to Svelte.** Run Claude Code inside this repo so it has the real context, and instruct it explicitly: implement as Svelte 5 components under `ts/`, style with the existing SCSS variable system in `ts/lib/sass`, do not introduce React or Tailwind. Treat the bundle as the visual spec.

**3. Land the tokens first (the durable design system).** Add pgrep tokens to `ts/lib/sass` (the `$vars` map that `_root-vars.scss` turns into CSS variables), including the warm neutrals, the amber, blue, and lilac data colors, and `--font-ui` and `--font-mono`. Add `@font-face` for Inter and JetBrains Mono (or the Fontsource imports). Light and dark ride the existing `.night-mode` class. Verify with `just fix-minilints` (licenses) then `just lint`.

**4. Build the components as Svelte, following Anki's patterns.** Put pgrep surfaces under `ts/routes/` (they are served as pages) and shared primitives under a pgrep components folder next to `ts/lib/components`. Reuse the icon pattern in `ts/lib/components/icons.ts` (add Lucide via the same `.svg?component` import), MathJax for equations, and the D3 conventions in `ts/routes/graphs` for the reliability diagram and coverage bar. Build the manifold as a Three.js surface with the 2D D3 contour fallback.

**5. Wire each surface to the engine.** Frontend talks to the backend through the generated `@generated/backend` TypeScript module (proto to Rust services over POST). Per L2, define the frontend to backend API first, which RPCs each surface calls: the points-at-stake selector and `get_queued_cards` for Study, the attempt log for grading, and the coverage and calibration snapshots for Home and Progress. The L1 Rust selector and the Problem and Attempt notetypes in `technical-architecture.md` are the data these read and write.

**6. Run and iterate.** `just run` launches Anki with the pages served at `http://localhost:40000/_anki/pages/`. Use `just web-watch` for live reload while building the surfaces. Finish with `just check`.

**Reality check on the handoff:** because the auto-handoff biases React and Tailwind, expect to use Claude Design as the source of truth for the look and the tokens, and to implement the Svelte components deliberately in the repo rather than pasting generated React. The tokens and the component spec transfer cleanly, the framework does not.
