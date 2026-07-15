# Shadow foundry and blind human calibration, design

Date: 2026-07-15. Status: approved for implementation planning. Author: pair
session.

This design covers the next content-foundry step after the calibrated verifier,
preference schema, leakage firewall, and standing evaluation landed. It adds
real multi-model generation in a quarantine-only shadow mode, constructs a
representative human ruler, and unlocks automated acceptance only after the
human and held-out gates pass.

The objective is not to generate the largest pool. It is to maximize the number
of near-perfect Physics GRE problems that survive the automated loop while
keeping correlated model errors, evaluator leakage, and human review load
visible.

Related design:
[`content-foundry-and-verifier-design.md`](content-foundry-and-verifier-design.md).
Operational details remain in
[`../reference/content-pipeline.md`](../reference/content-pipeline.md).

Implementation plans:

- [`multi-model-shadow-runner-plan.md`](multi-model-shadow-runner-plan.md)
- [`blind-calibration-ruler-plan.md`](blind-calibration-ruler-plan.md)

## Locked decisions

- Use a **shadow foundry** before enabling online acceptance. Shadow candidates
  cannot enter the bundle or preference dataset.
- The user labels the complete human ruler personally.
- Human labels are fully blind to model identity, stored key, verifier verdicts,
  recommendations, and confidence.
- The review artifact is Markdown, with machine-parseable answer lines and
  detailed instructions.
- Collect 120 primary judgments plus 12 hidden repeats for intra-rater
  consistency.
- Use a full problem-quality rubric: answer key, stem clarity, distractors,
  figure, difficulty, source grounding, decomposition leakage, and overall
  disposition.
- Use three frontier model families for candidate diversity: GPT-5.6 Sol,
  Claude Opus 4.8, and Grok 4.5.
- A model cannot be the primary judge of a candidate it generated.
- Human labels, deterministic checks, and held-out evidence outrank model votes.
- Do not fine-tune or distill a verifier in this step.

## Why shadow mode comes first

Calibrating only on the shipped pool would miss the future generator's error
distribution. Enabling online filtering before calibration would create
selection bias because the uncalibrated verifier would decide which examples
the human ever sees.

Shadow mode resolves both problems:

1. Generate raw candidates from the exact model portfolio and prompts intended
   for future production.
2. Quarantine all output, without accept or preference-pair side effects.
3. Mix those raw candidates with known-good and known-bad examples.
4. Label the mixture blind.
5. Fit thresholds on the predeclared calibration split.
6. Evaluate once on the locked human validation split and external held-out
   evidence.
7. Enable acceptance only after every gate passes.

## Architecture

The next step adds four isolated units:

1. **Provider-neutral model seam.** A small protocol accepts a strict request
   and returns text plus a run manifest. Existing OpenAI calls and the Cursor
   SDK adapter implement this protocol.
2. **Sandboxed multi-model shadow runner.** It retrieves corpus context, sends
   the same evidence and schema to each generator family, validates the
   response, and writes quarantined candidates.
3. **Blind calibration-set builder.** It creates the predeclared 120-item ruler,
   12 hidden repeats, and two Markdown review passes without exposing model or
   verifier metadata.
4. **Calibration importer and unlock controller.** It validates human labels,
   measures repeat consistency, fits thresholds on calibration only, runs the
   locked evaluations, and writes an explicit locked or unlocked decision.

Data flow:

```text
corpus-only retrieval
  -> sandboxed Sol / Opus / Grok shadow generation
  -> raw schema + provenance + deterministic validation
  -> quarantined candidate pool
  -> stratified blind 120-item ruler (+ 12 hidden repeats)
  -> human Markdown labels
  -> import + consistency checks
  -> calibration threshold fit (80 items)
  -> locked human validation (40 items)
  -> external held-out checks
  -> unlock decision
```

No arrow from shadow generation reaches `assemble_bundle.py` or
`preferences.jsonl`.

## Multi-model orchestration

### Model discovery

The checked-in runner never assumes that a display name is a callable model ID.
At startup it calls `Cursor.models.list()` and records each model's ID, its
`parameters`, and its `variants` as reported to the calling account.

The desired roles are:

- GPT-5.6 Sol, high reasoning effort
- Claude Opus 4.8, high reasoning effort
- Grok 4.5, high reasoning effort

If an exact requested model is unavailable, the run fails. It does not silently
substitute another model or use `auto`.

OpenAI's direct adapter follows the same rule. It prefers an exact snapshot. A
floating alias may produce quarantined exploratory candidates, but those
candidates are marked non-reproducible and cannot unlock acceptance or produce
training pairs.

### Cursor SDK boundary

The first shadow runner uses the Python Cursor SDK because the content pipeline
is Python and the account already exposes all three model families.

Each model invocation is a one-shot `Agent.prompt()` call inside a disposable
Docker container. The first implementation is Docker-only and requires a
verified local Unix socket; it does not claim or silently accept another
runtime. Podman is explicitly not supported by this first implementation:

- local Cursor runtime inside the container, with an explicit temporary working
  directory;
- only the generated request directory mounted into the container;
- no repository checkout or parent project path visible to the process;
- no ambient setting sources;
- no MCP servers;
- only the selected corpus excerpts and strict output instructions in input;
- explicit API key dependency;
- disposal handled by the one-shot API.

The sandbox directory contains no gold, human labels, held-out material, private
item files, or repository metadata. The container receives network access for
the Cursor API, an explicit `CURSOR_API_KEY`, and no other host credentials. A
working-directory convention alone is not treated as isolation because a local
agent could navigate elsewhere on the host. If no verified local Docker engine
is available, or the mount boundary cannot be verified for that request
directory, Cursor models are unavailable for private-corpus runs and the run
fails before the first prompt. The shipped first implementation has no
non-Docker fallback: an unavailable engine or unverifiable mount boundary is a
hard stop, never a reason to run a model on the host. The provider-neutral seam
still allows a future direct provider adapter, which would receive only the
explicit request payload, but no such adapter is wired into the shadow runner.

### Candidate allocation

The 40 shadow-generated calibration candidates are allocated as evenly as
possible:

- 14 from Sol
- 13 from Opus
- 13 from Grok

The extra candidate rotates on later runs. The allocation is also stratified by
blueprint category, problem kind, figure requirement, and intended difficulty.

After calibration, a best-of-eight production slot starts with a `3 / 3 / 2`
family allocation. The two-candidate family rotates by category and run. Future
allocation may change only from human-labeled, held-out evidence, not from raw
model self-scores.

### Cross-verification

Every candidate is solved blind by the two model families that did not generate
it. Choice order is independently shuffled for each solve.

- Sol candidate: Opus and Grok solve.
- Opus candidate: Sol and Grok solve.
- Grok candidate: Sol and Opus solve.

The originating model may provide a generation trace, but its own verdict is
not counted as independent evidence.

Model agreement is not sufficient for acceptance:

- SymPy or another deterministic contradiction rejects.
- Provenance or leakage failure rejects.
- Cross-model disagreement escalates.
- Agreement with insufficient calibrated support escalates.
- The human ruler defines whether model judgments are trustworthy.

### Role specialization

- **Sol:** primary quantitative generation and derivation.
- **Opus:** ambiguity, derivation coherence, and pedagogical-clarity critic.
- **Grok:** adversarial assumption, counterexample, and distractor critic.

All three still produce the same strict schema. These role prompts add
diversity; they do not change the acceptance contract.

Frontier solve rate is not a student-difficulty estimate. Difficulty continues
to use deliberately weaker proficiency profiles anchored to ETS evidence.

## Request and run manifests

Every call records:

- provider and exact model ID;
- advertised family and role;
- model parameters and reasoning effort;
- prompt version and SHA-256 prompt hash;
- output schema version;
- corpus chunk IDs and source references;
- randomization seed and displayed choice order;
- SDK version;
- agent ID and run ID;
- request time;
- repository commit;
- parser and retry outcome;
- reproducibility classification: exact snapshot or floating alias.

Each finalized run manifest also records an explicit `synthetic` boolean,
canonical SHA-256 hashes for every parsed candidate payload, and byte-level
SHA-256 digests for `candidates.json`, `failures.json`, and `probe.json`.
Consumers must verify those raw artifact bytes, payload hashes, and canonical
trace bindings before using a candidate. The blind ruler accepts only
`synthetic: false`, real-execution, clean, replayable `_SUCCESS` runs.

Raw transcripts and candidates live under git-ignored
`content/run/shadow-foundry/<run>/`. API keys and authorization headers are
never written.

## Strict output handling

The provider-neutral boundary returns text. The pipeline then:

1. Extracts exactly one JSON object.
2. Validates it against the problem schema.
3. Rejects non-finite numbers and unknown fields.
4. Validates five choices, key shape, provenance, and decomposition leakage.
5. Retries schema correction at most twice.
6. Records every failed response and reason.
7. Refuses the candidate after the retry budget.

No parser repair may invent physics content.

## Human ruler construction

### Primary composition

The 120 primary items contain:

- 40 trusted existing examples that are not drawn from gold or held-out sets;
- 40 known failures sampled from audit findings and rejected candidates;
- 40 raw shadow-generated candidates.

The set builder satisfies all of these constraints together:

- all nine blueprint categories represented;
- category counts approximately follow the PGRE blueprint while preserving
  minimum support;
- conceptual and computational items represented;
- figure-required and no-figure items represented;
- easy, medium, and hard intended bands represented;
- each model family represented in every feasible major stratum;
- known error modes represented: wrong key, free-elimination distractor,
  ambiguous stem, figure contradiction, unsupported citation, decomposition
  leak, and out-of-band difficulty.

The set manifest is frozen before labeling. Each item receives an opaque content
hash. Model origin and quality stratum remain in the private manifest, not the
review sheet.

### Calibration and validation split

Before the sheet is rendered, the 120 items are assigned:

- 80 to threshold fitting;
- 40 to locked human validation.

The assignment is stratified and hidden from the reviewer. The 40 validation
items are never used to select prompts, thresholds, or model allocation.

If the locked validation gate fails, the team may revise the system, but it
cannot retune against those 40 labels and call them held out again. A fresh
validation slice is required.

External ETS-held-out material remains separate. It may evaluate answer-key and
difficulty behavior, but it never appears in generation context, model prompts,
preference pairs, or calibration-set selection.

### Hidden repeats

Twelve items are repeated under different review IDs and positions. They do not
increase the 120-item fitting or validation support.

Repeat agreement is reported per property. The exact-answer repeat floor is
11 of 12 matching responses. Every other categorical property requires raw
repeat agreement at or above 0.90. Falling below either floor pauses threshold
fitting and requests adjudication; it is not blamed on the verifier.

## Blind Markdown review

Blinding and the full rubric require two Markdown passes.

The private, git-ignored review workspace is:

```text
content/run/calibration/<run-id>/
├── index.md
├── manifest.json
├── figures/
│   ├── item-0001.svg
│   ├── item-0002.svg
│   └── ...
├── pass-a/
│   ├── block-01.md
│   ├── block-02.md
│   └── ...
├── pass-b/
│   ├── block-01.md
│   ├── block-02.md
│   └── ...
└── reports/
```

Each block contains at most 20 judgments. `index.md` lists review IDs and
completion placeholders only. It does not show content hashes, model identity,
stored answers, verifier output, split assignments, or any other token that
would let a reviewer detect hidden repeats.

### Pass A: independent problem judgment

Pass A shows:

- stem;
- choices;
- a relative link to a per-review figure asset, when present.

Raw SVG never appears in Markdown. Each display review ID, including a hidden
repeat, gets a distinct `figures/<review-id>.svg` path. Pass A block files link
to that asset as `../figures/<review-id>.svg`. The asset bytes are the exact
UTF-8 encoding of the SVG validated and preserved by the immutable item schema.
The importer receives those bytes separately, decodes them strictly, and uses
them with the unprotected visible stem and choices to recompute `pass_a_hash`.
It must use the renderer's reversible unprotect function instead of deleting
zero-width or other characters.

It hides:

- stored answer;
- solution and decomposition;
- source excerpt;
- model family;
- model reasoning;
- verifier decisions;
- recommendations;
- calibration or validation split;
- repeat identity.

For each item, the reviewer records:

```text
your_answer: A | B | C | D | E | UNSURE
stem_clear: PASS | FAIL | UNSURE
distractor_A: VALID | INVALID | CORRECT_ANSWER | UNSURE
distractor_B: VALID | INVALID | CORRECT_ANSWER | UNSURE
distractor_C: VALID | INVALID | CORRECT_ANSWER | UNSURE
distractor_D: VALID | INVALID | CORRECT_ANSWER | UNSURE
distractor_E: VALID | INVALID | CORRECT_ANSWER | UNSURE
figure: MATCHES | CONTRADICTS | UNNECESSARY | MISSING | N_A | UNSURE
difficulty: 1 | 2 | 3 | 4 | 5 | UNSURE
overall: KEEP | DROP | UNSURE
notes:
```

### Pass B: grounding and leakage judgment

Pass B is generated only after Pass A imports successfully. It shows the cited
source excerpt and decomposition for the same opaque item, but still hides model
identity, stored verifier verdicts, and recommendations.

The reviewer records:

```text
source_supports_stem: PASS | FAIL | UNSURE
source_supports_answer: PASS | FAIL | UNSURE
decomposition_correct: PASS | FAIL | UNSURE
decomposition_leaks_answer: PASS | FAIL | UNSURE
notes:
```

### Instructions printed at the top of both sheets

The generated sheets include these instructions:

1. Work independently. Do not use another AI system.
2. In Pass A, solve the problem before consulting any outside reference.
3. A calculator and scratch work are allowed.
4. Use `UNSURE` instead of guessing.
5. Judge the presented problem, not how easily it could be repaired.
6. Mark a distractor valid only if it is wrong, distinct, and plausibly caused
   by a learner misconception.
7. Judge a figure against the prose, not against the hidden intended answer.
8. Do not infer model identity from writing style.
9. Do not edit item IDs or machine-parseable field names.
10. Complete Pass A and import it before opening Pass B.

The Pass A header also prints the allowed value set for every rubric field.
This legend does not prefill any item field.

The importer rejects incomplete values, unknown labels, duplicate review IDs,
changed content hashes, exposed model metadata, and edits to immutable problem
text.

## Calibration and unlock rules

The existing standing-eval gates remain authoritative:

- calibration and validation split isolation;
- minimum item and class support;
- post-threshold held-out agreement and balanced accuracy;
- accepted precision at or above 0.95;
- Wilson and bootstrap lower-bound requirements;
- measured consistency;
- figure and key properties present;
- sufficient finalized slots and categories;
- escalation point and confidence bound at or below 0.15;
- leakage, provenance, duplicate, and schema gates clean.

Additional unlock conditions:

- hidden-repeat agreement passes the predeclared human-consistency floor;
- each generator family has enough labeled shadow examples to report its error
  profile;
- no family-specific key or leakage failure is concealed by aggregate metrics;
- the first 20 automatically accepted post-unlock candidates receive a human
  audit before bundle landing is enabled.

The report compares the 5.6 portfolio with the recorded 5.5 baseline as
historical context, but that non-paired comparison is not an unlock gate.
Absolute human and held-out gates decide whether the new portfolio is safe.

The unlock controller writes one of:

- `LOCKED`, with failed checks and evidence;
- `SHADOW_ONLY`, when evaluation is incomplete;
- `ACCEPTANCE_ENABLED`, when every check passes;
- `LANDING_ENABLED`, only after the first-20 accepted audit also passes.

No command-line flag can bypass a locked state.

## Failure handling

- Missing requested model: fail before any candidate call.
- SDK startup failure: report separately from a model run failure.
- Retryable SDK error: honor retry metadata, then bounded exponential backoff.
- Model run error: record agent/run IDs and fail that candidate.
- Invalid JSON/schema: at most two correction attempts.
- Missing provenance: refuse candidate.
- Gold or held-out path/marker: fail the run and the leakage gate.
- Duplicate content hash: exclude before ruler sampling.
- Partial model portfolio: keep artifacts for diagnosis, but do not build the
  human ruler.
- Interrupted run: no `_SUCCESS` marker; downstream readers ignore it.
- Incomplete human sheet: refuse import and preserve the original file.

## Testing

Per-commit tests are offline:

- fake Cursor model listing and one-shot responses;
- exact model-role resolution;
- empty sandbox and no ambient setting sources;
- strict parser and retry budget;
- generator-origin exclusion from judging;
- deterministic allocation and randomization;
- calibration-set stratification;
- no held-out or gold references in prompts/manifests;
- two-pass Markdown round trip;
- blind-sheet metadata absence;
- hidden-repeat assignment and consistency;
- calibration/validation overlap rejection;
- locked-state transition table;
- no bypass of the unlock controller.

On-demand integration checks:

- account model probe;
- one candidate per model family on synthetic corpus context;
- manifest completeness;
- explicit confirmation that requested model IDs were used;
- shadow run over private corpus;
- blind sheet generation;
- human import;
- standing evaluation and unlock report.

## Non-goals

- No bundle landing from shadow output.
- No preference-pair emission from shadow output.
- No in-app live-generation change.
- No generator fine-tuning.
- No distilled verifier.
- No use of frontier solve rate as student difficulty.
- No replacement of human labels with model consensus.
- No use of gold or held-out text in any model prompt.

## Implementation sequence

1. Add the provider-neutral request/result protocol and Cursor SDK adapter.
2. Add account model probing, exact role resolution, and manifests.
3. Add the sandboxed multi-model shadow runner.
4. Add deterministic 40/40/40 ruler construction and hidden repeats.
5. Add blind Pass A Markdown generation/import.
6. Add Pass B grounding/leakage generation/import.
7. Add human-consistency and split manifests.
8. Connect imported labels to the standing evaluator.
9. Add the unlock controller and transition report.
10. Run the real shadow portfolio, generate the user's sheets, and pause for
    labeling.

Implementation should remain split into small reviewable branches or commits,
with fake-client tests before any real model call.
