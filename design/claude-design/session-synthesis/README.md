# Session synthesis

The end-of-session consolidation screen for pgrep's Study door. Shown once, when the last problem of a session is committed. It replaces the problem canvas; it is not a modal.

Files

- `Session Synthesis.dc.html` — dark, 1440×900
- `Session Synthesis Light.dc.html` — light, same structure, palette swapped
- Canonical in-context versions live in the project root, screen `2a` of `Study.dc.html` and `Study Light.dc.html`

## Philosophy

**One line.** pgrep is an honest physics instrument that renders your readiness beautifully. This screen is where a session's evidence is consolidated into something the student can carry out of the room.

**Truth first, warmth from reframing.** The score is stated plainly (14 / 20, monospace, large) and immediately reframed, "In-session accuracy understates your learning." That sentence is the voice rule in action. Warmth never comes from praise ("Great job!"), only from an honest, more useful reading of the same number. Desirable-difficulty study sessions are supposed to feel worse than they went; saying so is the kindest true thing available.

**Patterns, not a replay.** The center of the screen is not a question-by-question log. Misses are grouped into named patterns ("Moment of inertia taken about the wrong axis", "2 misses") because the pattern is the transferable unit, a student can fix an axis habit, not "question 7". Each pattern card carries one sentence of evidence with the actual physics set in real math (MathJax), per the editorial-physics identity. Equations look like a good textbook, never ASCII approximations.

**Name the wins too, but only real ones.** One card credits a strategy that worked ("Limiting cases are doing real work", "2 saves"). It earns its place by being evidence, not encouragement. If a session has no such pattern, the card is omitted, never invented.

**No review detour.** Problems already carry their decompositions in the ladder, so there is no "review misses" action here. Consolidation happened during the session; this screen names it. One exit: Done.

**Closes the loop with the selector.** The footer line "Tomorrow's selector weights these patterns" tells the student the synthesis is not a report card, it is an input. The system visibly acts on what it just told you.

**What is deliberately absent.**

- No calibration UI. Calibration is model calibration and lives in Progress, never a per-session confidence recap.
- No streaks, XP, confetti, or grade letters. The instrument does not celebrate; it reports.
- No per-question table. Progressive disclosure, patterns here, evidence ledger in Progress.
- No em-dashes and no colon-heavy phrasing in any copy (locked copy rule).

## Anatomy

Top bar (edge of panel, 20px 28px padding)

1. Progress counter `20 / 20` (JetBrains Mono 13, muted). Continuity with the in-session counter, now full.
2. Status chip "Session complete" (accent blue text, 1px accent-tinted border, pill). The only accent use outside data.
3. Close ✕ (32px ghost button, hover reveals background).

Content column (640px, centered, flows top to bottom)

1. Kicker `SESSION SYNTHESIS` (11px, 500, 0.08em tracking, uppercase, muted).
2. Headline score `14 / 20` (JetBrains Mono 44px, tabular-nums) with `correct · 48 min` beside it (15px muted). Baseline-aligned.
3. Reframe sentence (15px, 1.6 line-height, muted, max-width 540px).
4. **By topic.** One row per topic, grid `150px 1fr 56px`, a 6px pill-shaped bar (track = border color, fill = accent blue) and a mono fraction right-aligned. Bars are proportion correct, no percentages shown, fractions stay honest about small n.
5. **Patterns across the session.** Stacked cards (10px gap). Each card, raised surface, 1px border, 16px radius, 18/20px padding, faint shadow. Title row = pattern name (15px, 600) + count chip (mono 11px pill). Chip is muted for misses, accent for saves. One evidence sentence below (14px muted, real math inline).
6. Footer, pinned to bottom via `margin-top: auto`. Selector note left (13px, faintest text tier), primary Done button right (high-contrast fill, 10px radius, 11/24px padding).

## Palette

Dark, canvas `#1B1A19`, panel `#262624`, raised card `#302F2C`, border `#45433E`, text `#ECEAE3`, muted `#A5A199`, faint `#6E6B64`, accent `#81A1C1`.

Light, canvas `#EFECE6`, panel `#FBFAF8`, raised card `#FFFFFF`, border `#E8E4DA`, text `#262624`, muted `#6E6B64`, faint `#A5A199`, accent `#5E81AC`.

Accent blue appears exactly three times, status chip, topic bar fills, saves chip. It is a data language (performance), never decoration. No green/red verdict colors anywhere on this screen.

## Type

- Inter 400/500/600 for prose and UI.
- JetBrains Mono 400/500 for every number (counter, score, fractions, count chips), always with `font-variant-numeric: tabular-nums`.
- Scale used, 44 score, 15 body/titles, 14 evidence, 13 mono data, 12 chip, 11 kickers and count chips.

## Build notes

- Design Component, inline styles only, hover states via `style-hover`.
- Math is written as `\( … \)` in copy; the logic class polls for MathJax and calls `typesetPromise()` on mount and update (`startup.typeset` is false so streaming markup is not typeset twice).
- Load order in helmet, Google Fonts (Inter + JetBrains Mono), MathJax config before the MathJax script, body reset with the canvas color.
- The panel is a flex column with `min-height: 900px`; the content column uses `flex: 1` + `margin-top: auto` on the footer so Done sits at the bottom even if patterns are few.
- Sample data is illustrative. Real data contract, session fraction, duration, per-topic fractions, 1–4 pattern cards each with `{title, count, kind: miss|save, evidence}`.
