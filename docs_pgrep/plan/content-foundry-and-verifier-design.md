# pgrep content foundry and calibrated verifier, design

Date: 2026-07-07. Updated: 2026-07-14. Status: Phase 1 and Phase 2 are
merged. Phase 3 is implemented on `feat/pgrep-foundry-dataset-eval`. The human
calibration set and the numeric Tier trigger counts are not yet achieved.
Author: pair session.

This spec describes a verification-guided content foundry for pgrep: generate
many candidate problems, pass each through a calibrated verifier panel, and emit
only the ones that clear every gate with margin. The goal is to maximize the
yield of near-perfect problems that survive the automated loops, so almost
nothing junky reaches the human reviewer. It is written to split into small,
mostly independent branches that can run in parallel.

Implementation plans (TDD, task-by-task):

- Phase 1 verifier:
  [`content-foundry-and-verifier-plan.md`](content-foundry-and-verifier-plan.md)
  (merged)
- Phase 2 foundry loop:
  [`content-foundry-loop-plan.md`](content-foundry-loop-plan.md) (merged)
- Phase 3 dataset and standing eval:
  [`content-foundry-dataset-and-eval-plan.md`](content-foundry-dataset-and-eval-plan.md)
  (implemented on `feat/pgrep-foundry-dataset-eval`)

## Context

pgrep is a Physics GRE study app forked from Anki. The AI content pipeline turns
the open corpus into the shipped `content_bundle.json` (cards, problems,
decompositions, figures). Its architecture is in
[`../reference/content-pipeline.md`](../reference/content-pipeline.md); the data
and eval methodology are in [`dataset-pipeline.md`](dataset-pipeline.md) and
[`../ai/ai-layer.md`](../ai/ai-layer.md).

The pipeline already has a research-grade eval scaffold: a gold ruler (157
verified items in `content/gold/`), held-out ETS forms (`content/tier3-private/`),
pre-registered cutoffs with bootstrap CIs (`content/tools/eval_metrics.py`), an
LLM judge (`pylib/anki/pgrep/ai/judge.py`), and an independent SymPy verifier
(`pylib/anki/pgrep/ai/verify.py`). What it lacks is a verifier we can _trust_,
and a loop that uses it to lift generation quality.

### The problem, in numbers

From `content/run/score_report.json` and the last AI audit:

- **The judge does not agree with the human.** Inter-rater kappa is `-0.03`
  (useful) and `0.14` (fact precision) over 73 rated items. The judge on record
  was a `mini` model producing a single holistic score. A verifier with near-zero
  human agreement cannot gate quality, and cannot safely drive any training loop.
- **Raw generator yield is mediocre.** Problem key correctness `0.69`, distractor
  quality per problem `0.67`, useful yield `0.64`. Card fact precision `0.90`.
  All below the pre-registered cutoffs (problem key `0.95`, distractor `0.70`,
  useful `0.75`; card fact `0.95`).
- **The audit on the shipped bundle surfaced a real backlog:** ~10 genuinely
  wrong figures and 171 "free elimination" distractors.

### Objective

Build the durable system first (a trustworthy verifier plus a standing loop),
then use it to regenerate and grow the pool. Fine-tuning is staged and only
happens once the data earns it. Concretely, maximize the count of problems that
pass the whole verifier panel with margin, while keeping the human escalation
rate low.

### Prior art folded in

A Hugging Face paper sweep informed the design. The techniques adopted and their
sources:

- Verify the reasoning, not just the final answer.
  [DeepSeekMath-V2, 2511.22570](https://huggingface.co/papers/2511.22570).
- Generative, reasoning-first verifiers with vote.
  [GenRM, 2408.15240](https://huggingface.co/papers/2408.15240);
  [RM-R1, 2505.02387](https://huggingface.co/papers/2505.02387).
- Backward verification (mask a given, recover it from the key).
  [FOBAR, 2308.07758](https://huggingface.co/papers/2308.07758).
- Multi-agent cumulative verification for physics specifically.
  [PhysicsEval, 2508.00079](https://huggingface.co/papers/2508.00079).
- Verification scales with the candidate pool, but an imperfect verifier at large
  N can prune all good candidates and underperform plain sampling.
  [Sample, Scrutinize and Scale, 2502.01839](https://huggingface.co/papers/2502.01839);
  [Scaling Flaws of Verifier-Guided Search, 2502.00271](https://huggingface.co/papers/2502.00271).
- Calibrate reliability on two axes: human alignment and intrinsic consistency.
  [Diagnosing LLM-as-a-Judge via IRT, 2602.00521](https://huggingface.co/papers/2602.00521);
  [JudgeBench, 2410.12784](https://huggingface.co/papers/2410.12784).
- Position bias in judging is real; randomize order and require consistency.
  [Judging the Judges, 2406.07791](https://huggingface.co/papers/2406.07791).
- A good distractor is one a weaker solver actually falls for.
  [Do LLMs Make Mistakes Like Students?, 2502.15140](https://huggingface.co/papers/2502.15140);
  [DisGeM, 2409.18263](https://huggingface.co/papers/2409.18263).
- Do not use a strong model's solve-rate as difficulty; strong models converge to
  a machine consensus misaligned with human difficulty. Use proficiency
  simulation and anchor to real ETS difficulty.
  [Can LLMs Estimate Student Struggles?, 2512.18880](https://huggingface.co/papers/2512.18880).
- Prefer SFT with a strong teacher before DPO/RLAIF.
  [A Critical Evaluation of AI Feedback, 2402.12366](https://huggingface.co/papers/2402.12366);
  aggregate diverse solutions rather than self-select
  [GSA, 2503.04104](https://huggingface.co/papers/2503.04104).

## Design principles

- **One seam per concern.** Reuse the existing seams rather than fork them: the
  `llm.LLMClient` for every model call, the `Judge` for single checks, `verify.py`
  for SymPy and deterministic leak checks, `eval_metrics.py` for CIs,
  `review_sheet.py` for human sheets, `assemble_bundle.py` for the gated landing.
- **Trust from objective and consensus checks, not one fuzzy judge.** Keys,
  distractor wrongness, and leaks are decided by SymPy, multi-model consensus, and
  backward checks. Only the genuinely soft residual (misconception plausibility,
  difficulty) leans on a subjective call, and that is what gets escalated.
- **High-precision accept, then escalate.** The panel is tuned so an `accept`
  almost never passes junk, even at the cost of escalating more items. This is the
  direct mitigation for the verifier-guided-search failure mode.
- **Everything offline-testable.** Every module runs against a fake client with no
  network, following the `test_pgrep_judge.py` pattern. Real-model runs are
  on-demand via `just` recipes, never in CI.

## Non-goals (for this phase)

- No generator fine-tuning yet (Tier 3, staged below).
- No distilled cheap verifier yet (Tier 2, staged below).
- No IRT machinery; the two-axis idea (alignment, consistency) is adopted, the
  Graded Response Model math is not.
- No change to the shipped bundle schema or the per-commit invariant gate.

## Architecture overview

Data flow:

```
generate best-of-N  ->  verifier panel  ->  accept (clean)      -> assemble_bundle.py -> bundle
   (llm seam)            (per-check          reject (+reason)     -> preference dataset
                          verdicts,          escalate (low conf)  -> human sheet (review_sheet.py)
                          confidence,
                          evidence)
        ^                                                              |
        |______________________ thresholds retuned ___________________|
                         (calibration harness + human labels)
```

Components, each an isolated, testable unit:

1. **Verifier panel** (`pylib/anki/pgrep/ai/verifier.py`, new) composes the
   single checks into one `PanelVerdict` with an overall `accept` / `reject` /
   `escalate` decision, a confidence, and evidence per check.
2. **Consensus key verification** (`pylib/anki/pgrep/ai/consensus.py`, new):
   multi-model solve plus SymPy plus backward check, generalizing the existing
   three-opinion logic in `crosscheck_keys.py` onto the `llm` seam.
3. **Distractor validity and temptation** (part of the panel): each option
   re-solved for wrongness, plus a temptation score from weaker solvers.
4. **Difficulty estimation** (`pylib/anki/pgrep/ai/difficulty.py`, new):
   proficiency-simulated solvers anchored to held-out ETS difficulty.
5. **Calibration harness** (`content/tools/calibrate_verifier.py`, new): per
   property agreement and consistency against a human-labeled set, emits a
   calibration card and the per-gate thresholds the panel reads.
6. **Best-of-N foundry loop** (`content/tools/foundry.py`, new): sample, verify,
   partition into accept / reject / escalate, report yield.
7. **Preference dataset emitter** (part of the loop): chosen/rejected pairs for
   Tier 3.
8. **Standing eval** (`just` recipes plus an offline smoke in `test-py`).

## Workstreams

Each workstream is independently shippable unless a dependency is noted. The
dependency order is roughly WS1 -> {WS2, WS3, WS4, WS5} -> WS6 -> WS7 -> {WS8,
WS9}.

### WS1. Verifier panel skeleton

- Add `pylib/anki/pgrep/ai/verifier.py` with a `PanelVerdict` dataclass and a
  `Verifier` class that composes the checks. Each sub-check contributes a typed
  sub-verdict carrying `passed: bool`, `confidence: float`, and `evidence: str`.
- The panel decision is `accept` when every hard gate passes above its threshold,
  `reject(reasons)` when a hard gate fails with confidence, and `escalate` when
  any hard gate is within a low-confidence band. Thresholds are read from a config
  file written by WS6 (a checked-in default until calibrated).
- Reuse the injectable `_Client` seam from `judge.py`; the panel takes a
  generator client and a distinct judge client so no model grades its own output.
- Acceptance: `Verifier.check(problem)` returns a `PanelVerdict` with per-check
  sub-verdicts and an overall decision; unit tested with a fake client; no
  network; importing the module does not import `openai` or `sympy` eagerly.

### WS2. Consensus key verification

- Add `pylib/anki/pgrep/ai/consensus.py` that decides a problem's key from three
  independent signals: (a) N diverse model solves through `llm` (distinct dated
  snapshots, default N=3, configurable), (b) SymPy via `verify.cas_equivalent` /
  `verify.cas_check_value` for computational items, and (c) a FOBAR backward check
  that masks a given quantity, supplies the proposed key, and asks the model to
  recover the quantity. The key is accepted when SymPy agrees, or when the
  backward check passes and at least a strict majority of the N solves agree with
  the stored key.
- Require the solve to include a reasoning trace and check that the trace is
  coherent, not only that the final letter matches (per DeepSeekMath-V2). A right
  letter with an incoherent derivation does not pass.
- Position-bias control: shuffle option order across solves and require answer
  stability; instability lowers confidence and can trigger escalation.
- Generalize the `crosscheck_keys.py` verdict table (consensus, one-model-slip,
  likely-wrong, hard-3way) into reusable functions on the `llm` seam, not the raw
  OpenAI client, so both the gold cross-check and the panel share it.
- Acceptance: given a problem, returns a consensus verdict with per-solver
  opinions, the SymPy result when applicable, the backward-check result, and a
  confidence; offline tests with fakes cover a known-correct key (passes), a
  known-wrong key (rejected), and an unstable-under-shuffle case (escalates).

### WS3. Distractor validity and temptation

- In the panel, add a distractor check with two parts: (a) each distractor is
  genuinely wrong, decided by re-solving each option (reuse the consensus solver);
  (b) a temptation score equal to the fraction of weaker or proficiency-simulated
  solvers that select that option. A distractor with zero temptation is a "free
  elimination" and fails the soft gate (this is exactly the 171-flag class).
- Provide a two-stage generator helper (generate candidate distractors, then
  select) for use at generation time, per DisGeM.
- Acceptance: returns per-distractor `{is_wrong, temptation, verdict}`; a script
  can re-score the 171 flagged problems; offline tests with fakes cover a strong
  distractor (tempting) and a free-elimination distractor (flagged).

### WS4. Figure, giveaway, leak, and citation checks

- Wrap the existing `Judge.figure_fidelity`, `Judge.technique_giveaway`, the
  deterministic `verify.find_giveaway` decomposition-leak check, and the citation
  resolver into panel sub-verdicts, each emitting a confidence. Apply the position
  and consistency controls where a check compares items or options.
- Preserve the existing `audit_bundle_ai.py` behavior; the audits and the panel
  share the same underlying checks.
- Acceptance: these checks return panel-compatible sub-verdicts; the existing
  audit output is unchanged; offline tests confirm parity with current behavior.

### WS5. Difficulty estimation

- Add `pylib/anki/pgrep/ai/difficulty.py` that estimates a problem's difficulty
  from an ensemble of weaker or proficiency-simulated solvers, not from a frontier
  model's solve-rate. Output a difficulty band and a flag when a problem falls
  outside the PGRE band.
- Calibrate and validate against real ETS item difficulty from the held-out forms
  in `content/tier3-private/items/`, which carry known difficulty. Report the
  correlation between the estimate and ETS difficulty.
- Acceptance: produces a difficulty estimate per problem; a validation script
  reports correlation against held-out ETS difficulty; the documented caveat from
  2512.18880 is recorded next to the method.

### WS6. Calibration harness and calibration card

- Build a stratified, per-property human-labeling set of ~120 items across the
  nine blueprint categories, seeded from the 73 already-rated AI items and the
  gold set. Emit and ingest a per-property sheet (key, each distractor, figure)
  through `review_sheet.py`.
- Add `content/tools/calibrate_verifier.py` that runs the panel over the labeled
  set and reports, per property: raw agreement, balanced accuracy, precision, and
  recall (extend `eval_metrics.py` with balanced-accuracy and per-property
  helpers; it already has `cohens_kappa` and bootstrap CIs). Also report intrinsic
  consistency: verdict stability under prompt perturbation and option shuffles.
- Tune each gate threshold for high accept-precision and write the thresholds to
  the config the panel reads. Emit a calibration card as JSON plus Markdown under
  `content/run/calibration/`.
- Acceptance: produces the calibration card with both axes (alignment and
  consistency) and per-gate thresholds; the panel reads the written thresholds;
  offline-tested on a tiny synthetic labeled set.

### WS7. Best-of-N foundry loop

- Add `content/tools/foundry.py`: for each blueprint slot, sample N diverse
  candidates through `llm` (default N=8, configurable), run each through the
  calibrated panel, keep the clean survivors, log every reject with its reason,
  and route split or low-confidence items to a human escalation sheet.
- Cap N by the calibration-measured verifier accuracy, so a weak verifier does not
  over-prune (the 2502.00271 failure mode). Add a comparative verification pass
  that lets the verifier see multiple candidates together and identify errors by
  contrast (per 2502.01839).
- Accepted problems land through the existing gated `assemble_bundle.py`; the
  per-commit invariant gate is unchanged.
- Acceptance: given a slot spec, emits `{accepted[], rejected[+reason],
  escalated[]}` and a per-category yield report; deterministic under a seed; a
  dry-run mode runs offline with fakes.

### WS8. Preference dataset emitter

- The loop logs every candidate with its panel verdict and reason as
  chosen/rejected pairs in a stable, documented schema under
  `content/run/foundry/`. Chosen means passed all gates; rejected records the
  specific failing gate and its evidence.
- Respect the firewall: the dataset is git-ignored, grounds only on the corpus,
  and never contains gold, held-out, or ETS material.
- Acceptance: the schema is documented and validated; a small run produces a
  well-formed dataset; a leakage check confirms no gold or ETS content.

### WS9. Standing eval and gate wiring

- Add a `just eval-verifier` recipe that runs the calibration set plus a held-out
  slice as a regression eval, printing the two-axis calibration card and yield
  with bootstrap CIs. Add a tiny offline smoke to `just test-py` so the panel and
  loop logic stay green per commit without any network.
- Acceptance: the recipe runs and prints the calibration card and yield; the
  offline smoke runs in `test-py`.

## Staged tiers (future gates)

These are future training gates, not claims that training has started. The
human calibration set is not complete, the `300`-problem and `1000`-pair
counts have not been reached, and no Tier 2 or Tier 3 training has begun.

- **Tier 2, distilled verifier.** Once the panel is calibrated and there are
  enough panel-labeled items (target: a few hundred consensus-labeled problems),
  distill the panel into one cheap generative verifier (GenRM / RM-R1 style,
  reasoning-first) so the gates run cheaply at high volume. Trigger: calibration
  card accept-precision at or above `0.95` on key and figure, and at least `300`
  panel-labeled problems available under `content/run/foundry/` (operator-counted;
  that tree is git-ignored).
- **Tier 3, generator fine-tune.** Start with SFT on the panel-accepted problems
  from the strong generator (per 2402.12366, SFT-first often beats a DPO/RLAIF
  pipeline). Add DPO on the chosen/rejected pairs only if SFT plateaus. Use GSA
  aggregation for the canonical worked solutions. Trigger: preference JSONL with
  at least `1000` validated pairs across at least `6` blueprint categories,
  leakage check clean, and the Phase 3 standing eval green on the latest
  calibration card.

## Testing strategy

- Offline unit tests with a fake `LLMClient` for every panel check, following
  `pylib/tests/test_pgrep_judge.py`.
- Deterministic tests for the SymPy path, the backward check, consensus voting,
  threshold application, and escalation routing.
- The calibration harness tested on a small synthetic labeled set.
- The standing-eval smoke runs offline in `test-py`.
- No network in CI. Real-model runs are on-demand via `just` recipes with a key.

## Firewall

Unchanged and reaffirmed. Generation reads only `content/corpus/`. Gold,
held-out, and ETS material never enter the corpus, the index, a prompt, or the
preference dataset. The foundry outputs stay git-ignored under `content/run/`.

## Risks and mitigations

- **Verifier over-pruning at large N.** Gate for high accept-precision, cap N by
  measured verifier accuracy, keep the human escalation path. (2502.00271)
- **Judge self-preference and vendor bias.** Distinct dated snapshots for
  generator and judge, SymPy as a model-independent check, option-order shuffles,
  human adjudication of escalations.
- **Difficulty misalignment.** Proficiency simulation and ETS anchors, never
  frontier solve-rate. (2512.18880)
- **Cost.** Budget is not the binding constraint, but N is still capped by
  verifier accuracy, because past that point more samples hurt.

## Success criteria

- **Verifier trust:** on the calibration card, per-property raw agreement at or
  above `0.90` and balanced accuracy at or above `0.85` (key agreement the
  strictest), with intrinsic consistency at or above `0.90`. These are the initial
  bars; calibration (WS6) may tighten them. This replaces the single misleading
  kappa.
- **Content quality of the accepted set:** key correctness at or above the
  existing `0.95` cutoff, distractor quality per problem at or above `0.70`, zero
  free-elimination distractors, and figure fidelity passing.
- **Yield and human load:** report the candidates-to-accepted ratio per category,
  with an escalation rate low enough to be sustainable (target near or below
  15 percent of candidates reaching a human).

## Module map

New:

- `pylib/anki/pgrep/ai/verifier.py` (panel)
- `pylib/anki/pgrep/ai/consensus.py` (multi-model key consensus, backward check)
- `pylib/anki/pgrep/ai/difficulty.py` (proficiency-simulated difficulty)
- `content/tools/calibrate_verifier.py`
- `content/tools/foundry.py`
- tests: `test_pgrep_verifier.py`, `test_pgrep_consensus.py`,
  `test_pgrep_calibration.py`, `test_pgrep_foundry.py`

Touched:

- `pylib/anki/pgrep/ai/judge.py` (sub-verdict confidence)
- `content/tools/eval_metrics.py` (balanced accuracy, per-property agreement,
  consistency helpers)
- `content/tools/review_sheet.py` (per-property sheet variant)
- `content/tools/crosscheck_keys.py` (reuse the generalized consensus)
- `justfile` (`eval-verifier`, foundry recipes)
- docs: `../reference/content-pipeline.md`, `../ai/ai-layer.md`
