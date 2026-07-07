# Session consolidation and tutor anti-spam, design

Date: 2026-07-06. Status: approved for planning. Author: pair session.

This spec covers two additions to the decomposition tutor (the Problems-door miss
flow) plus one explicit cut. It follows the tutor work already shipped
(`docs_pgrep/plan/2026-07-06-ui-ux-and-decomposition-tutor-design.md` and the
gated tutor in `pylib/anki/pgrep/decomposition.py`).

## Context

The Problems door opens a gated decomposition tutor on a miss: 2 to 3 subproblems,
each an MCQ (unlimited retries, a wrong pick shows only that distractor's
rationale) plus, with AI on, a lenient "explain why" the AI must pass. The parent
answer is never revealed; the missed problem re-queues with new numbers. Scoring
already excludes tutor retries (``ladder_depth >= 1``).

Two gaps remain from `feature-productive-failure.md`:

1. Session-end consolidation is computed but not shown. The backend
   `tutor.session_synthesis` (exposed as `pgrepTutorSynthesis`) returns a recap,
   patterns, principles, and a calibration line, AI-on summarized or AI-off
   templated, but no surface renders it.
2. There is no safeguard against brute-forcing a subproblem MCQ.

## Decisions locked with the product owner

- Consolidation leads with the conceptual **synthesis** (discriminating
  principles), not the numbers.
- Consolidation ships in two places from one component: the real Problems session
  end and a harness preview.
- Anti-spam is **gentle friction on detected gaming only**, invisible to honest
  learners, with a calm nudge when it triggers.
- Anti-spam concentrates on the **MCQ** (a temporary hold plus option-order
  shuffle on retry). The AI explanation gate is its own safeguard, so no
  client-side "filler" heuristic is added (that would fight the grader leniency
  that passes short conceptual answers).
- **Adaptive fading is cut.** It contradicts the forced-learning identity, needs
  attempt history a fresh account lacks, and the 60 to 85 percent difficulty band
  already adapts coarsely. See the note at the end for the hook if revisited.

## Workstream 1: session-end consolidation

### Component

A reusable `ts/lib/components/SessionSynthesis.svelte` that renders the
`pgrepTutorSynthesis` payload. One component, two mount points, so tuning it once
tunes both. Synthesis-led layout, in the calm instrument voice, no em-dashes:

- **Carry forward** (leads): the 1 to 3 discriminating principles, each one short
  line. The far-transfer payload.
- **What tripped you**: the recurring confusions (patterns), a short list.
- **Recap** (quiet, at the bottom, small and muted): "You answered X of Y
  first-try," the per-topic accuracy, and the calibration line.

Honesty holds: on thin data or AI off, the backend already templates patterns and
principles from the attempt log, so the component always has honest content and
never fabricates. Score hues stay reserved; this surface is monochrome text.

### Real session end

The Problems session end already fetches synthesis (`fetchSynthesis` in
`ts/routes/pgrep/study/+page.svelte`). Render `SessionSynthesis` there in the
end-of-session state instead of the current bare completion.

### Harness preview

The tutor harness (`ts/routes/pgrep-lab/tutor/+page.svelte`) does not run a real
session, so add a **Preview consolidation** control backed by a new dev endpoint
`pgrepTutorSynthesisPreview` (handler in `qt/aqt/pgrep.py`, body in
`anki.pgrep.tutor`) that builds a synthesis from a small fixed sample attempt set.
This renders the same `SessionSynthesis` component so the screen can be tuned
without playing a full session. Dev-only, never wired to a shipped surface.

### Acceptance

- Finishing a Problems session shows the consolidation, synthesis first, recap
  quiet at the bottom.
- The harness Preview shows the same component on sample data.
- AI off still shows templated patterns and principles, never a fabricated number.

## Workstream 2: tutor anti-spam (gentle friction)

Client-side in `SubproblemCard.svelte`, no scoring impact (scoring already
excludes tutor retries). All thresholds live in one constants block for tuning.

### MCQ temporary hold

Track wrong-pick timing per subproblem. After 2 rapid wrong picks (each within a
short window of the rationale appearing, initial threshold ~2.5s), hold the Check
button for a brief growing cooldown (initial ~2s) and show a calm one-line nudge,
"Take a moment with this before trying again." The rationale must have been
visible for a minimum beat before Check re-enables. Honest learners who read
between attempts never see it.

### MCQ option-order shuffle on retry

On each retry of a subproblem MCQ, shuffle the displayed choice order and re-letter
by display position, so cycling by position or by remembered letter both fail. The
displayed letter maps back to the choice's stored key before grading, so
`decomposition.check_mcq` still receives the correct original key. The correct and
distractor semantics are unchanged; only presentation order changes.

### Explanation gate

No new client heuristic. With AI on, the existing lenient grader is the safeguard:
a learner cannot advance without a passing explanation, so brute-forcing the MCQ
alone never advances the step. With AI off there is no explanation gate, so the
MCQ hold and shuffle above carry the anti-spam load, which is the only surface
where gaming is possible.

### Acceptance

- Rapid repeated wrong MCQ picks trigger a short hold and a calm nudge; a normal
  paced learner never sees it.
- Retrying a subproblem MCQ reorders the choices; a selected choice still grades
  against its true key.
- No explanation is ever rejected for being short or fast; only the AI grade (or
  a blank) can fail it.

## Cut: adaptive fading

Not built. If revisited, the hook is recent per-topic clean first-try accuracy
(already in the attempt log and read by the Performance model): a strong recent
record could shorten the tutor or drop the explanation gate. Deferred because it
fights the forced-learning identity, cold-starts poorly, and adds branching and
answer-leak surface for little gain over the existing difficulty band.

## Touches

- New: `ts/lib/components/SessionSynthesis.svelte`.
- Edit: `ts/routes/pgrep/study/+page.svelte` (render at session end),
  `ts/routes/pgrep-lab/tutor/+page.svelte` (Preview control),
  `ts/lib/components/SubproblemCard.svelte` (hold + shuffle + nudge),
  `ts/lib/components/ChoiceList.svelte` (accept a shuffled, re-lettered order if
  needed).
- Backend: `qt/aqt/pgrep.py` (`pgrepTutorSynthesisPreview` handler),
  `pylib/anki/pgrep/tutor.py` (sample-based preview synthesis).

## Non-goals

- No change to scoring, the selector, the sync engine, or the parent-answer
  withholding guarantee.
- No change to the grader's leniency; anti-spam does not touch the explanation.
- No adaptive fading.
