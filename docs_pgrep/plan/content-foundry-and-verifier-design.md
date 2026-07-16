# pgrep content foundry and calibrated verifier, design

Date: 2026-07-07. Updated: 2026-07-16. Status: Phases 1–3 and the shadow/ruler
code are on `main`. Online shadow runs and human ruler handoff are **paused**
until WS10 (usage ledger + budgets) lands. Tier trigger counts are not achieved.
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
  (merged)
- Shadow generation and blind calibration:
  [`shadow-foundry-calibration-design.md`](shadow-foundry-calibration-design.md),
  [`multi-model-shadow-runner-plan.md`](multi-model-shadow-runner-plan.md),
  [`blind-calibration-ruler-plan.md`](blind-calibration-ruler-plan.md)
  (code on `main`; Pass A handoff / Pass B incomplete; paid runs paused for WS10)

## Current status board (2026-07-16)

Single place to see where the content-quality program stands. Learner-facing
packaging todos remain in [`deferred-todos.md`](deferred-todos.md).

### Done / landed

| Track | State |
| --- | --- |
| Phase 1 — consensus key check, verifier panel, agreement metrics | On `main` |
| Phase 2 — temptation, difficulty, best-of-N foundry loop | On `main` |
| Phase 3 — preference dataset + `just eval-verifier` | On `main` (human labels / green gate card not achieved) |
| Shadow multi-model runner + blind ruler modules | On `main` (Tasks 1–5-ish; Pass B / handoff incomplete) |
| Triple-pool content growth (problems, figures, decomps, audits) | Ran; bundle grew (~378 problems, high decomp coverage). Quality still needs the calibrated gate |
| Credential posture | Direct provider keys removed from `content/.env` and shell exports. One TrueFoundry gateway file: `~/.config/truefoundry/gateway.env`. `llm.load_api_key` + `LLMClient` route via `OPENAI_BASE_URL` |

### Paused / missing (blocks safe resumption of expensive loops)

| Gap | Why it matters |
| --- | --- |
| **WS10 — usage ledger, budgets, kill switch** (below) | No central token/$ accounting on `LLMClient`. Ad-hoc counters exist in a couple of old tools only. Cannot answer spend-to-date or stop a runaway batch |
| Ruler Task 6–7 (Pass B + real Pass A handoff) + human labels | Needed before calibrated unlock |
| Tier 2 / Tier 3 training triggers | Still future; numeric counts (`300` labeled problems, `1000` pairs) not reached |

### Recommended resume order

1. Implement **WS10** (ledger + soft/hard caps) and set an explicit daily hard cap.
2. Finish shadow/ruler only behind those caps; prefer TFY model IDs (`gpt-5.5`,
   `claude-opus-4-8`, `grok-4.5`) over Cursor SDK for generation volume.
3. Complete Pass A handoff → human labels → Pass B → unlock standing eval.
4. Only then grow the pool with online foundry acceptance.

### Model roles (TFY gateway — locked preference)

| Role | Gateway model id | Notes |
| --- | --- | --- |
| Default generator | `gpt-5.5` | Bulk stems, decomps, figures |
| Hard cross-judge | `claude-opus-4-8` | Origin-excluding key/figure/giveaway checks |
| Diverse second opinion | `grok-4.5` | Blind re-solve / temptation diversity |
| Cheap weak solver (optional) | `gpt-5.4-mini` or `claude-haiku-4-5` | Distractor temptation / difficulty sim |

Floating gateway IDs replace dated OpenAI snapshots for TFY-routed runs. The
dated-snapshot pin rule in `LLMClient` needs a TFY-aware exception or a
gateway-id allowlist before production recipes rely on it.

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
- Tune each gate threshold for high accept-precision on the calibration split
  only, then apply that fixed cutoff to the held-out split. Each threshold
  records whether the 0.95 target is attainable, its nullable cutoff, achieved
  precision, retained count, and eligible count. Emit a calibration card as JSON
  plus Markdown under `content/run/calibration/`.
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

- The loop emits pairs only for validated accepted by rejected combinations
  from the same blueprint slot. Chosen means passed all gates; rejected records
  the specific failing gate and its evidence. Escalations and one-sided slots
  make no pairs. `panel.refusal` outcomes are explicitly excluded, and run
  summaries report their counts and reasons. A malformed accepted or rejected
  training candidate fails the run closed; no final directory or `_SUCCESS`
  marker is published.
- Schema v1 preserves the slot topic and blueprint category, requires source
  references on both sides, and validates panel decisions, reject evidence,
  reject reasons, JSON-compatible values, and finite numbers. The category is
  one of the nine exact slugs locked in `../ai/blueprint.md`; variants are
  invalid.
- Each pair declares whether it is synthetic. Dry-run pairs are synthetic and
  excluded from training counts. Non-synthetic source references must exist in
  the corpus index. Cross-run audits detect duplicate chosen and rejected
  identities and expose eligible pair and category counts.
- Writes overwrite atomically within a new run and reject duplicate ID pairs.
  An exclusive sibling lock closes the publication race. `_SUCCESS` is written
  immediately before atomic rename; aggregators and leakage checks read only
  finalized, non-temporary run directories.
- Real accepted verifier checks may have empty evidence. Non-synthetic chosen
  items still need a non-empty check list, and no chosen item may contain a
  failed hard check.
- Respect the firewall: default output under `content/run/foundry/` is
  git-ignored, grounds only on the corpus, and never contains gold, held-out, or
  ETS material. Operators are responsible for keeping custom output paths
  private and out of version control.
- Acceptance: the schema is documented and validated; a small run produces a
  well-formed dataset; a leakage check confirms no gold or ETS content.

### WS9. Standing eval and gate wiring

- Add a `just eval-verifier` recipe that requires explicit calibration and
  held-out property-label splits. Threshold selection reads calibration only;
  held-out labels and confidences cannot influence the cutoff. Held-out records
  contain opaque aligned item IDs, labels, and numbers only and remain
  evaluation-only. Duplicate property IDs and any cross-split overlap are
  invalid. IDs must be stable hashes or IDs from a frozen manifest, not
  per-execution row numbers.
- Print split-specific reports, threshold diagnostics, and a standing gate card.
  Headline held-out agreement, balanced accuracy, precision, and recall are
  computed after applying the calibration cutoff; pre-threshold metrics remain
  diagnostics.
- Green requires key and figure; 30 examples with five human positives and five
  human negatives per required property in each split; post-threshold agreement
  at least 0.90; balanced accuracy at least 0.85; consistency at least 0.90 over
  30 items; and at least 20 retained key and figure accepts. Key and figure
  accepted precision point, percentile-bootstrap lower bound, and deterministic
  95% Wilson lower bound must all be at least 0.95.
- Foundry uncertainty bootstraps slot-level yield and escalation rates through
  `eval_metrics.bootstrap_ci`. Headline rates are the unweighted means of the
  same non-empty slot rates; candidate-weighted values are pooled diagnostics.
  Six non-empty slots across six valid categories are required for green.
  Escalation point and interval upper bound must both be at most 0.15. Legacy
  aggregate summaries report points only.
- `--foundry-summary` accepts one JSON file or a foundry root whose run
  summaries are aggregated recursively. `--preferences-root` exposes the
  cross-run Tier 3 audit in the report. Directory aggregation excludes
  finalized synthetic runs and reports the excluded count.
- Acceptance: the recipe always prints or writes a structurally valid report.
  Red exits nonzero. The offline self-check supplies at least 100 all-correct
  retained accepts plus passing per-slot foundry data and exits 0.

### WS10. Usage ledger, budgets, and kill switch

**Problem.** Every paid call eventually goes through `llm.LLMClient` (or a
bypass in a few legacy tools), but the seam does not record tokens, estimate
USD, or enforce a cap. After a ~$2000 bill spike, expensive shadow/foundry work
must not resume without precautionary controls.

**Non-goals.** No full accounting product; no syncing the ledger; no dependence
on scraping a vendor invoice UI in CI. TrueFoundry’s own dashboard remains the
invoice source of truth; the local ledger is the **run-time** control plane.

**Design.**

1. **Record at the seam.** Every successful (and failed-with-usage) completion
   in `LLMClient` appends one JSONL event under the git-ignored tree
   `content/run/usage/<yyyy-mm-dd>.jsonl`. Fields (v1):

   - `ts` (UTC ISO), `run_id` (optional env `PGREP_USAGE_RUN_ID`), `tool`
     (optional `PGREP_USAGE_TOOL`), `model`, `ok`
   - `prompt_tokens`, `completion_tokens`, `total_tokens` (from the response
     `usage` object when present; else null)
   - `est_usd` (float or null) from a small local price table keyed by model
     family; unknown models log tokens with `est_usd: null` and still count
     toward a **token** cap if configured
   - `base_url_host` (hostname only of `OPENAI_BASE_URL`, never the key)

2. **Price table.** A checked-in, manually maintained map
   `pylib/anki/pgrep/ai/usage_prices.py` (or YAML beside it) with rough
   USD/1M-token rates for the TFY portfolio we care about (`gpt-5.5`,
   `claude-opus-4-8`, `grok-4.5`, minis). Estimates are explicitly approximate;
   the ledger never claims invoice accuracy.

3. **Budgets (env + optional local file).** Resolved once per process:

   | Control | Env / file | Default behavior |
   | --- | --- | --- |
   | Soft daily USD | `PGREP_BUDGET_SOFT_USD` | Log warning; continue |
   | Hard daily USD | `PGREP_BUDGET_HARD_USD` | Raise / abort before the next call |
   | Hard daily tokens | `PGREP_BUDGET_HARD_TOKENS` | Same abort path |
   | Per-run USD | `PGREP_BUDGET_RUN_USD` | Abort within one `run_id` |
   | Disable paid calls | `PGREP_AI_SPEND_LOCK=1` | Fail closed immediately |

   Optional operator file (git-ignored): `content/run/usage/budget.env` sourced
   by `just` recipes the same way as the TFY gateway. Caps are **fail-closed**
   when a hard limit is set and the ledger cannot be read/written.

4. **Kill switch before the call.** `LLMClient.complete_*` loads today’s
   ledger totals (plus the current run) and refuses the network call if a hard
   cap would be exceeded. Soft caps only warn (stderr + a `budget_soft` event).

5. **Operator surface.**

   - `just usage-report` — today / last N days: tokens, est USD, by model, by
     tool/run_id
   - `just usage-smoke` — one tiny TFY completion that must appear in the
     ledger and respect a tiny hard cap in the smoke’s env
   - Foundry/shadow/audit recipes set `PGREP_USAGE_TOOL` and a fresh
     `PGREP_USAGE_RUN_ID` so batches are attributable

6. **Bypass cleanup.** Legacy tools that still construct a raw `OpenAI()`
   client must either call through `LLMClient` or call a shared
   `usage.record(...)` helper. No new bypasses.

7. **Firewall / privacy.** The ledger stays under `content/run/` (git-ignored).
   Events must never include prompts, completions, API keys, or corpus text —
   metadata and counts only.

**Acceptance.**

- Offline unit tests: fake client returns `usage`; ledger line written; hard
  cap blocks the next call without network; soft cap does not block; lock env
  blocks; missing price → tokens recorded, `est_usd` null, token cap still
  works.
- `just usage-smoke` (network, TFY) writes one event and exits 0 under a
  generous cap; exits nonzero when `PGREP_BUDGET_HARD_USD=0` (or equivalent).
- Docs in [`../reference/content-pipeline.md`](../reference/content-pipeline.md)
  describe the env knobs and the ledger path.
- **Gate:** no shadow-foundry, foundry online, or full-bundle AI audit run is
  considered approved until WS10 is green and a hard daily USD cap is set in
  the operator’s environment.

**Suggested starting caps (operator-chosen; not code defaults).** Soft
$25/day, hard $50/day, per-run $20, until a month of TFY invoices calibrates
the price table. Code defaults are “no cap” so CI and offline tests stay quiet;
operators must set hard caps for real work.

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
  at least `1000` validated non-synthetic pairs across at least `6` locked
  blueprint categories, no cross-run duplicate or audit error, leakage check
  clean, and the Phase 3 standing eval green on the latest calibration card.
  Foundry summaries expose the current eligible pair and distinct-category
  counts for this audit. The current design does not claim either count has
  been reached.

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
preference dataset. Default foundry output stays under the git-ignored
`content/run/foundry/` tree. Custom output paths remain the operator's
responsibility.

## Risks and mitigations

- **Verifier over-pruning at large N.** Gate for high accept-precision, cap N by
  measured verifier accuracy, keep the human escalation path. (2502.00271)
- **Judge self-preference and vendor bias.** Distinct dated snapshots for
  generator and judge, SymPy as a model-independent check, option-order shuffles,
  human adjudication of escalations.
- **Difficulty misalignment.** Proficiency simulation and ETS anchors, never
  frontier solve-rate. (2512.18880)
- **Cost.** Binding again after a large bill spike. N remains capped by
  verifier accuracy; **WS10** makes spend visible and enforces soft/hard caps
  before any multi-model or best-of-N online run.

## Success criteria

- **Verifier trust:** on held-out labels after calibration-only threshold
  fitting, every reported property has raw agreement at or above `0.90`,
  balanced accuracy at or above `0.85`, and measured consistency at or above
  `0.90`. Support minima are 30 examples, five examples per human class, and 30
  consistency items. Key and figure retain 20 accepts and have accepted
  precision point and lower confidence bound at least `0.95`. Missing evidence
  is red. These bars replace the single misleading kappa.
- **Content quality of the accepted set:** key correctness at or above the
  existing `0.95` cutoff, distractor quality per problem at or above `0.70`, zero
  free-elimination distractors, and figure fidelity passing.
- **Yield and human load:** report the candidates-to-accepted ratio per category,
  with an escalation rate low enough to be sustainable (target near or below
  15 percent of candidates reaching a human).

## Module map

New (Phases 1–3 / shadow — variously merged or branched):

- `pylib/anki/pgrep/ai/verifier.py` (panel)
- `pylib/anki/pgrep/ai/consensus.py` (multi-model key consensus, backward check)
- `pylib/anki/pgrep/ai/difficulty.py` (proficiency-simulated difficulty)
- `pylib/anki/pgrep/ai/temptation.py` (weak-solver distractor temptation)
- `pylib/anki/pgrep/ai/agreement.py` (per-property agreement / calibration card)
- `content/tools/calibrate_verifier.py`
- `content/tools/foundry.py`
- `content/tools/eval_verifier.py`
- tests: `test_pgrep_verifier.py`, `test_pgrep_consensus.py`,
  `test_pgrep_calibration.py`, `test_pgrep_foundry.py`, …

New for WS10 (not started):

- `pylib/anki/pgrep/ai/usage.py` (ledger append, totals, cap check)
- `pylib/anki/pgrep/ai/usage_prices.py` (approximate USD/1M rates)
- `content/tools/usage_report.py` + `just usage-report` / `just usage-smoke`
- tests: `test_pgrep_usage.py` (offline)

Touched:

- `pylib/anki/pgrep/ai/llm.py` (record usage; enforce caps; TFY `base_url`)
- `pylib/anki/pgrep/ai/judge.py` (sub-verdict confidence)
- `content/tools/eval_metrics.py` (balanced accuracy, per-property agreement,
  consistency helpers)
- `content/tools/review_sheet.py` (per-property sheet variant)
- `content/tools/crosscheck_keys.py` (reuse the generalized consensus)
- `justfile` (`eval-verifier`, foundry recipes, usage recipes, TFY gateway load)
- docs: `../reference/content-pipeline.md`, `../ai/ai-layer.md`,
  `../reference/content-and-dependencies.md`
