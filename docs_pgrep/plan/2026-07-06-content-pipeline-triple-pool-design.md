# Content pipeline: triple the problem pool, finish decompositions, verify diagrams

Status: design, awaiting review. Owner: Frank. Date: 2026-07-06.

## Purpose

Grow and complete the pgrep study content in one coordinated, verified pass:

1. Triple the standard problem pool, with an explicit, honest split between
   problems that require a diagram and problems that do not.
2. Finish the decomposition tutor data that was deferred (97 problems today have
   none).
3. Generate decomposition tutor data for every new problem.
4. Add numeric variants as needed so a repeated subproblem never reuses numbers.

Everything reuses the shipped, grounded, multi-pass verification that already
backs the content (cite-or-refuse, giveaway guard, CAS/SymPy, independent key
solve). Nothing uncertain ships without a human verdict. The app's runtime code
and the AI-off path stay untouched.

## Success criteria

- Problem pool goes from 137 to about 410 (triple: about 275 new), still
  weight-proportional across the nine blueprint areas, every item cited, zero
  em-dashes, no duplicate stems (including against the pre-existing bundle).
- About a third of the new problems are diagram-required. Every diagram-required
  problem ends with a valid, convention-passing SVG that an independent fidelity
  check confirms matches the described setup. Zero dangling figure references
  anywhere. Every text-only problem is verified figure-free.
- 100 percent decomposition coverage of the final pool. Each decomposition
  passes the giveaway guard, the independent solve, and the CAS check, and
  carries about three numeric variants per subproblem plus a renumbered parent
  variant.
- `tools/pgrep_content_audit.py --strict` passes; the pgrep Python tests pass;
  the AI-off import proof passes; the tutor harness lists every problem.
- Every item the machine could not clear was routed through a disposable review
  file and adjudicated by Frank.

## Current state (measured 2026-07-06)

- 342 cards, 137 problems, all cited, blueprint-balanced, zero em-dashes.
- 39 problems carry a figure, 98 are text-only. All 39 figures pass the SVG
  conventions.
- 40 problems have `decomposition_tutor`, 97 do not. The prior run made 40 (115
  subproblems, 225 variants) with a low drop rate.
- Toolchain confirmed working: `openai` 2.44.0, corpus index present, key in
  `content/.env`, model `gpt-5.5-2026-04-23` available.

Cards are out of scope for this effort. This is the problem pool only.

## Content authoring rules (locked)

- A diagram-required problem still describes its setup fully in prose, with all
  numeric values and units in the text. The figure carries only the symbolic
  geometry or topology (R, L, C, B, v, theta). The figure complements the words,
  it never replaces them. Example: "In the circuit shown, a battery of EMF
  \(\varepsilon\) drives current through ...", with the figure showing the
  arrangement.
- A text-only problem is fully self-contained in prose and LaTeX and references
  no figure.
- Copy rule everywhere: no em-dashes, short labels, honest voice.
- Grounding rule everywhere: cite a named corpus source or refuse. Gold and
  held-out data never enter a prompt.

## The five stages

Stages A and the deferred half of Stage C are independent and start in parallel.

### Stage 0: baseline and policy

- Back up `content_bundle.json` to `content_bundle.pre_triple.json`.
- Run the audit and record the baseline.
- Lock the topic-aware figure policy below.

### Stage A: grow the pool with diagram-aware generation

Driver work extends `content/tools/generate_content_set.py` with opt-in flags so
the existing gate-batch behavior is unchanged when the flags are absent:

- A grow mode that adds targets beyond the nominal blueprint set and assigns
  non-colliding ids (continue the `p4-prob-NNNN` sequence past the current max).
- A per-target `figure_required` stamp from the topic-aware policy.
- Instruction injection into the `topic` string passed to `generate_problem`, so
  a diagram-required target is told to author a figure-warranting setup
  (described fully in words) and a text-only target is told to stay
  self-contained. The shipped `PROBLEM_SYSTEM` prompt and the runtime authoring
  path are not modified.
- Deduplication against the existing bundle, in addition to the within-batch and
  reject-memorized checks already present.

Each problem is verified by the shipped core: cite-or-refuse, misconception-first
distractors, CAS on any computational expression, and an independent key solve
(`verify_key=True`). Items that refuse, fail the key solve, or fall below the
confidence threshold are flagged, not shipped.

Output: candidate problems with their `figure_required` flag and verify flags in
a per-batch run directory. Flagged items go to review file 1 (problems).

### Stage B: figures and the necessity/fidelity gate

For every `figure_required` problem, and only those:

- Draw the SVG with `tools/pgrep_figure_gen.py` (generate then refine).
- Verify conventions with the audit's figure checks: well-formed XML, a viewBox,
  `currentColor`, no hardcoded colors, no design tokens, no numeric or unit
  labels.
- Verify fidelity with a new independent AI check
  (`tools/pgrep_figure_verify.py`): a judge model, given the stem and the SVG,
  confirms the figure shows the components, geometry, and labels the stem
  describes, and is sufficient to reason about the problem. The judge is a
  different snapshot from the generator so it never grades its own drawing.

For every `figure_required: false` problem: a hard check that the stem contains
no figure reference (no "as shown", "figure", "diagram", "shown above/below").

Only figures that pass conventions and fidelity are wired with
`tools/pgrep_wire_figures.py`. Any figure that fails fidelity, or any problem
where the text and the figure disagree, goes to review file 2 (figures), which
links the light and dark preview from `pgrep_figure_gen.py`.

This closes the "randomly generating diagrams" gap: figure need is decided up
front per problem, the drawing is verified against the text, and no text-only
problem can imply a figure that does not exist.

### Stage C: decompositions to full coverage

Run `content/tools/generate_decompositions.py` for every problem that lacks
`decomposition_tutor`: the 97 deferred plus the roughly 275 new, about 372 total.

- Keep the multi-pass verification on (`verify_keys=True`): the giveaway guard so
  no subproblem leaks the parent answer, the independent solve for every MCQ key,
  and the CAS check on computational variants.
- Raise numeric variants per subproblem from two to about three, plus the
  renumbered parent variant. This is the "variants as needed" item.
- Selection and output are already per-id and per-directory, so subagents split
  the id list into batches, each writing its own run directory. Frank's process
  merges and applies.

Problems that yield fewer than two clean subproblems, or that trip repeated
key-unconfirmed flags, go to review file 3 (decompositions).

### Stage D: land and verify

- Merge the approved problems, figures, and decompositions into
  `content_bundle.json`, and update the `counts` metadata.
- Run `tools/pgrep_content_audit.py --strict` (hard invariants must pass:
  citations, copy rule, counts, figure conventions).
- Run the pgrep Python tests and the AI-off import proof.
- Smoke the tutor harness so it lists the full pool.
- Emit a coverage report: problem count by area, diagram versus text-only, and
  decomposition coverage (target 100 percent).

## Topic-aware figure policy

Diagram-required share per area, chosen so a figure is only ever required where a
diagram is genuinely natural. These are targets; the fidelity gate may drop some,
and finest-unit assignment refines which specific units carry diagrams (for
example, within mechanics, dynamics, rotation, and oscillations carry diagrams
while abstract energy arguments stay text-only).

| Area               | Blueprint | New (approx) | Diagram share | Diagram (approx) |
| ------------------ | --------- | ------------ | ------------- | ---------------- |
| mechanics          | 20%       | 55           | 50%           | 28               |
| electromagnetism   | 18%       | 50           | 45%           | 22               |
| quantum            | 13%       | 36           | 15%           | 5                |
| thermodynamics     | 10%       | 27           | 40%           | 11               |
| atomic             | 10%       | 27           | 15%           | 4                |
| optics_waves       | 8%        | 22           | 55%           | 12               |
| special_relativity | 6%        | 16           | 10%           | 2                |
| lab                | 6%        | 16           | 40%           | 6                |
| specialized        | 9%        | 25           | 15%           | 4                |
| Total              |           | ~274         | ~34%          | ~94              |

## Subagent orchestration

- Parallelize the generation-heavy stages with subagents. Each subagent owns a
  disjoint batch (by area for Stage A, by id list for Stage C) and writes to its
  own run directory. No subagent writes to `content_bundle.json`.
- The single writer to the shared bundle is the orchestrator (Frank's process),
  which merges the batch outputs, dedups, and applies. This keeps the shared seam
  race-free while the expensive work fans out.
- Use the best available snapshot for generation and a different snapshot for the
  judge and fidelity checks.

## Review convention (disposable files)

Anything the machine cannot clear is written to `content/run/review/` (private,
gitignored) as `NN-<stage>-<topic>.md`, one block per item, each ending with a
`-> your call:` slot:

- Problems: KEEP / FIX: <note> / DROP, plus the generated key and the independent
  solve when they disagree.
- Figures: KEEP / REDRAW: <note> / DROP FIGURE (make text-only) / KEEP TEXT-ONLY,
  with a link to the light and dark preview.
- Decompositions: KEEP / FIX: <note> / DROP, per subproblem when needed.

Frank fills the slots. The applier reads the verdicts, applies them, and deletes
the file. Nothing uncertain lands without a verdict.

## Tooling changes

- `content/tools/generate_content_set.py`: opt-in grow mode, `figure_required`
  policy and per-target stamping, instruction injection, dedup against the
  bundle. Defaults preserve current behavior.
- `content/tools/generate_decompositions.py`: variant-count knob (two to three),
  otherwise unchanged. Already supports `--ids` and `--out` for batching.
- `tools/pgrep_figure_verify.py` (new): the independent figure fidelity judge.
- Figure-reference check: extend `tools/pgrep_content_audit.py` (or a small
  sibling) to flag dangling figure references and `figure_required` mismatches.
- Review tooling: a small generator and applier for the disposable review files,
  modeled on `content/tools/make_content_review_sheet.py` and `apply_review.py`.
- A runbook capturing the exact commands and the batch split.

## Verification (the multi pass and the tests)

- In-pipeline, per item: cite-or-refuse, giveaway guard, CAS/SymPy, independent
  key solve, confidence routing (problems); giveaway guard, independent solve,
  CAS (decompositions); conventions plus fidelity (figures).
- Bundle-level: `pgrep_content_audit.py --strict`.
- Repo-level: the pgrep Python tests, the AI-off import proof, and the tutor
  harness smoke.

## Scale, cost, resumability

Tripling touches roughly three to four thousand model calls across the stages and
runs in the multiple-hours range even parallelized. Every stage checkpoints its
partial output, so the run is pausable and resumable, and a failed batch is
re-runnable by id without redoing the rest.

## Setup and isolation

Because this writes the shipped bundle and runs long, do the implementation in a
dedicated worktree and branch (for example `feat/content-triple-pool`) off the
latest main, per the worktrees rule, so the primary checkout stays undisturbed
while the user works elsewhere.

## Risks and mitigations

- Diagram fakery. Mitigated by up-front `figure_required`, the fidelity judge,
  and the dangling-reference check.
- Bundle duplication as the pool grows. Mitigated by the new dedup against the
  existing bundle.
- Rate limits and cost from fan-out. Mitigated by batch sizing, checkpoints, and
  a tunable subagent count.
- Shipped-path regressions. Mitigated by keeping runtime prompts and the AI-off
  path untouched, and by the strict audit plus the test suite before landing.

## Out of scope

Cards, the iOS Problems port, unrelated UI, and any change to the scoring or
scheduling models. Those stay as separate tracks.
