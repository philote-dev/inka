# Content pipeline: build, gate, and audit

The durable reference for how the content pipeline is built and kept honest: the
deep modules the tools share, the per-commit gate that guards the shipped bundle,
and the on-demand AI audits. The pipeline turns the open corpus into the shipped
`content_bundle.json` (cards, problems, decompositions, figures). The private
data it reads and the eval methodology are covered elsewhere:
[`dataset-pipeline.md`](../plan/dataset-pipeline.md) is the data status board,
[`content-and-dependencies.md`](content-and-dependencies.md) is sourcing and
provenance, and [`../ai/ai-layer.md`](../ai/ai-layer.md) is the generation and
evaluation methodology.

The design principle is one seam per concern. A single LLM client, a single
Judge, and a single review-sheet module replace the near-identical copies each
tool used to carry, so a behavior is defined and tested in one place.

---

## What is tracked, what is not

The pipeline code under `content/tools/` (roughly seventy Python tools) is
version-controlled, so the pipeline is reviewable and reproducible. The default
private data and run locations under `content/` are git-ignored: the corpus, the
gold and held-out sets, the RAG index, the run artifacts, the ETS raw-to-scaled
constants, `content/.env`, and the local databases. The copyrighted and held-out
material never enters git, while the code that operates on it does. An operator
who passes a custom output path is responsible for keeping it private and out of
version control. The deep modules the tools share live under
`pylib/anki/pgrep/` and ship with the app.

---

## One LLM seam

`pylib/anki/pgrep/ai/llm.py` `LLMClient` is the single seam for every model call.
It pins an exact dated model snapshot (it refuses a floating alias), uses a low
temperature and a seed when the snapshot supports one, retries transient errors
with a short backoff, and drops any option a snapshot rejects so the strongest
model still works. Its two public methods are `complete_text(system, user, *,
json_object=False)` for a raw completion and `complete_json(...)` for a parsed
JSON object. `load_api_key(...)` is the one place that resolves `OPENAI_API_KEY`
(the environment, then `content/.env`, then a repo-root `.env`), replacing the
per-tool copies. `openai` is imported lazily, so an AI-off app never loads it.

The figure generator (`tools/pgrep_figure_gen.py`), the figure judge
(`tools/pgrep_figure_verify.py`), and the technique-giveaway judge
(`content/tools/check_technique_giveaway.py`) all route through this client
instead of each holding a private OpenAI client and retry loop.

---

## One Judge

`pylib/anki/pgrep/ai/judge.py` `Judge` is one independent judge over an
injectable client: a real `LLMClient` in production, a fake injected through the
`client` seam in tests, so nothing in the module touches the network. Each check
is four small pieces (a system prompt, a payload builder, a typed verdict
dataclass, and a `Judge` method), and each method returns a typed verdict.
Figure fidelity and technique giveaway are methods on it; the audit checks
(`answer_key`, `distractor_plausibility`) extend it with the same four pieces. By
default the judge resolves a dated snapshot distinct from the generator, so a
model never grades its own output.

---

## One review sheet

`content/tools/review_sheet.py` backs the three make/apply review pairs (pool,
figure, giveaway) with one build/parse round-trip. A sheet is Markdown: a header,
then one `### <id>` block per flagged item, each ending in a machine-parseable
`-> your call:` line. The `make_*` scripts render sheets from flagged items; the
`apply_*` scripts read the filled verdicts back. Each stage supplies only what
differs (its id pattern, its default recommendation, and its block renderer),
while the parser, the assembler, and the default-recommendation manifest live
here once.

---

## The bundle gate (per-commit)

Bundle validity is a gate. `pylib/anki/pgrep/content_invariants.py` holds the
deterministic invariants over the shipped `content_bundle.json`:

- exactly five choices per problem, and a `correct` key in A-E that indexes a
  real choice;
- a non-empty stem, and a present `source_ref` on every problem;
- no duplicate ids across cards and problems, and no duplicate normalized problem
  stems or card fronts;
- balanced LaTeX delimiters in each prose field, counting genuine math and
  excluding escaped line breaks (for example a `cases` row break written
  `\\[4pt]`);
- a `counts` block that matches the actual card and problem counts;
- figure necessity: a stem that promises a figure ("as shown", "in the figure")
  carries an `<svg>`, and a `.pg-figure` wrapper contains one;
- valid decomposition variants when a `decomposition_tutor` is present (five
  choices and a key in A-E per variant).

The module is standard-library only, so it runs over the raw JSON without loading
the compiled app or any AI dependency. `pylib/tests/test_pgrep_content_invariants.py`
runs it over the shipped bundle under `just test-py`, so a bundle that regresses
fails CI and names the offending ids. The same module also backs the assembly
command, so the gate and the landing tool agree by construction.

`content/tools/assemble_bundle.py` is the single landing command in place of the
four-step runbook. It lands problems, decompositions, and text edits
(`land_triple.py`), converts bare math to delimited LaTeX (`pgrep_math_convert.py`),
wires the approved SVG figures (`pgrep_wire_figures.py`), then runs the invariants
and exits non-zero when a hard invariant fails. Steps can be skipped when their
inputs are not ready, and `--check-only` gates the current bundle without running
any step.

---

## The AI audits (on-demand)

`content/tools/audit_bundle_ai.py`, run via `just audit-bundle-ai`, is a
pre-release or nightly scan of the shipped bundle, not a per-commit gate. Every
audit rides the shared `Judge` seam (a real judge in production, a fake in
tests). It runs five audits:

| Audit                     | Kind          | Severity | What it checks                                                                                   |
| ------------------------- | ------------- | -------- | ------------------------------------------------------------------------------------------------ |
| `answer_key`              | LLM           | HARD     | Independently re-solve each problem, blind to the stored key, and flag disagreements.            |
| `figure_fidelity`         | LLM           | HARD     | For each `pg-figure` problem, judge whether the SVG faithfully depicts the figure-stripped stem. |
| `decomposition_leak`      | deterministic | HARD     | Run the giveaway verifier on each decomposition variant against the parent's answer.             |
| `distractor_plausibility` | LLM           | SOFT     | Flag wrong options that are obviously wrong and free to eliminate.                               |
| `citation`                | deterministic | SOFT     | Check each `source_ref` resolves against the corpus index; skips when the index is absent.       |

The HARD audits (`answer_key`, `figure_fidelity`, `decomposition_leak`) make the
run exit non-zero when they find something; the SOFT audits
(`distractor_plausibility`, `citation`) report only. The run writes a JSON report
and a Markdown summary under `content/run/audit/`.

---

## The verifier panel and calibration (Phase 1)

Beyond the on-demand audits, the pipeline has a calibrated verifier panel that
renders a single accept / reject / escalate decision per problem, built to gate
generated content before it reaches a human.

`pylib/anki/pgrep/ai/consensus.py` decides whether a stored answer key is correct
from three independent signals: several diverse model solves through the `llm`
seam (with the option order shuffled to check position stability), an optional
SymPy check (`verify.cas_check_value`) for items that carry an explicit answer
expression, and an optional FOBAR backward check (mask a given value, then try
to recover it from the proposed answer). A deterministic disproof wins outright.
Otherwise a stable majority carries. Confidence is measured over the solves that
actually answered and is down-weighted when most calls failed, so a couple of
failed API calls never masquerade as a confident reject.

`pylib/anki/pgrep/ai/verifier.py` composes that key consensus with the existing
single-check judges (figure fidelity, technique giveaway, distractor
plausibility) into a `PanelVerdict`. Key and figure are hard gates. Giveaway and
distractor are soft, so they annotate the verdict but do not change the
decision. The rule is one threshold: a hard check that fails with confidence at
or above `certain` (default 0.8) rejects, any hard check below `certain`
escalates, and otherwise the panel accepts. The panel and the audits share the
same underlying checks.

`pylib/anki/pgrep/ai/agreement.py` holds the calibration statistics, stdlib-only
so they ship with the app: per-property raw agreement, balanced accuracy,
precision and recall, verdict consistency under perturbation, and a
precision-target threshold sweep. Together they form a calibration card that
reports, property by property, how well the panel agrees with human judgment.
This replaces the single, misleading Cohen's kappa the old audit reported.

---

## The content foundry loop (Phase 2)

Phase 2 turns the verifier panel into a best-of-N generation loop: sample many
candidates per blueprint slot, verify each, and keep only the survivors. Design
and phasing live in
[`content-foundry-and-verifier-design.md`](../plan/content-foundry-and-verifier-design.md)
and the task plan
[`content-foundry-loop-plan.md`](../plan/content-foundry-loop-plan.md).

### Temptation (soft panel check)

`pylib/anki/pgrep/ai/temptation.py` scores each candidate whose label differs
from the stored key by how often weaker or proficiency-simulated solvers select
it. Here "wrong" means only "not the stored key"; the panel's key consensus owns
whether that stored key is correct. With at least one valid weak solve, zero
temptation is a free elimination (the same failure mode the
`distractor_plausibility` audit flags). With no valid solves, the report has no
free eliminations. When `weak_clients` are wired into `Verifier`, a `temptation`
check joins the panel as SOFT: it records free-elimination labels in the verdict
but does not change the accept / reject / escalate decision until temptation is
calibrated.

### Difficulty estimate (caveat)

`pylib/anki/pgrep/ai/difficulty.py` estimates an easy / medium / hard band from
weak solvers, not from a frontier model's solve-rate. Per
[2512.18880](https://huggingface.co/papers/2512.18880), that distinction matters:
a hard item for a strong model can look easy when scored by solve-rate alone.
The module is available, but difficulty estimation is not yet wired into the
foundry or verifier loop. That integration is deferred. Validation against
held-out ETS item difficulty is an offline evaluation only; the Pearson helper
is for content tools, not CI.

### Foundry partition and N cap

`pylib/anki/pgrep/ai/foundry_loop.py` owns the sample-verify-partition loop.
`run_slot` generates N candidates for one blueprint slot, runs each through the
panel, and partitions results into `accepted`, `rejected`, and `escalated`.
`max_n_for_accuracy` caps N from calibrated verifier accuracy (floor 2, ceiling
8) so a weak verifier cannot over-prune a large candidate pool.

`content/tools/foundry.py` is the CLI. Offline modes never touch the network:
`--self-check` for smoke, `--dry-run` for a full partition with fakes. The CLI
caps requested `--n` using `--verifier-accuracy` (conservative default 0.8).
`--category` records the blueprint category and defaults to `mechanics`; topic
may remain more specific. The category must be exactly one of the nine locked
lowercase slugs.
Online generation will use the same partition once wired. Comparative
multi-candidate selection (`--compare`) is deferred to Phase 2.1.

### Escalation sheet and firewall path

Each persisted foundry run writes four JSON files under
`content/run/foundry/<run>/`: `accepted.json`, `rejected.json`,
`escalated.json`, and `summary.json`. It writes `preferences.jsonl` beside
them. Run `content/tools/make_foundry_escalation.py` to render a Markdown
review sheet (`ESCALATE` / `KEEP` / `DROP` per item) from the latest run by
default, or pass `--run <name>`. The CLI refuses an existing run directory. It
builds and validates the pairs first, writes every artifact to a temporary
sibling, verifies the preference count, then atomically publishes the complete
directory. An exclusive sibling lock file closes the final check and rename
race; lock and temporary state are removed on success or failure. Timestamp run
IDs include microseconds. Default artifacts stay under the ignored
`content/run/foundry/` tree; custom `--out` paths are the operator's
responsibility. Generation still reads only `content/corpus/`.

Accepted survivors still land only through `assemble_bundle.py` and the
per-commit invariant gate.

---

## The preference dataset and standing eval (Phase 3)

Phase 3 adds a stable preference format and a standing offline
evaluation. It does not start verifier distillation or generator training. The
implementation plan is
[`content-foundry-dataset-and-eval-plan.md`](../plan/content-foundry-dataset-and-eval-plan.md).

### Preference pairs

`pylib/anki/pgrep/ai/preference.py` defines schema v1 through
`preference_schema_version = 1`. Each JSONL record has these fields:

```json
{
    "schema": 1,
    "synthetic": false,
    "slot": {
        "topic": "thin lenses",
        "blueprint_category": "optics_waves"
    },
    "chosen": {
        "id": "candidate-1",
        "stem": "...",
        "choices": ["...", "...", "...", "...", "..."],
        "correct": "A",
        "source_ref": "corpus://openstax/example",
        "panel": {
            "decision": "accept",
            "checks": [
                {
                    "name": "key",
                    "passed": true,
                    "severity": "hard",
                    "evidence": "independent solve agrees"
                }
            ]
        }
    },
    "rejected": {
        "id": "candidate-2",
        "stem": "...",
        "choices": ["...", "...", "...", "...", "..."],
        "correct": "B",
        "source_ref": "corpus://openstax/example",
        "panel": {
            "decision": "reject",
            "checks": [
                {
                    "name": "key",
                    "passed": false,
                    "severity": "hard",
                    "evidence": "independent solve disagrees"
                }
            ]
        },
        "failing_gates": ["key"],
        "reason": "key: independent solve disagrees",
        "refused": false
    },
    "run_id": "run-1"
}
```

`validate_pair` enforces non-empty run and slot fields, distinct IDs, five
non-empty choices, an `A` through `E` key, source references, the required panel
decisions, a non-empty reject reason, and panel evidence. A normal rejection's
`failing_gates` must exactly match its failed hard-check names. A refusal instead
uses `refused: true`, `failing_gates: ["refusal"]`, and a non-empty reason.
Recursive validation permits only JSON-compatible values and string object
keys; sets, tuples, object instances, NaN, and infinities fail before
serialization. Invalid construction or writing raises `ValueError`; no record
is silently skipped.

The locked category vocabulary is `mechanics`, `electromagnetism`, `quantum`,
`thermodynamics`, `atomic`, `optics_waves`, `special_relativity`, `lab`, and
`specialized`. Case, whitespace, spelling, and separator variants are rejected
rather than normalized.

Only validated accepted by rejected combinations from the same slot become
pairs, capped at 64 per call. Escalations, invalid candidates, and slots lacking
either side produce no pair. A non-positive cap produces zero pairs.

`content/tools/foundry.py` atomically overwrites one new run's
`preferences.jsonl`; it never appends to an earlier run. Duplicate chosen and
rejected ID combinations fail the write. Every pair has an explicit
`synthetic` boolean. Dry-run pairs are synthetic and can exercise the pipeline,
but they never count toward training readiness. `summary.json` includes its
`blueprint_category` plus a `preferences` object with total validated count,
non-synthetic pair count, distinct eligible category count, and category names.
These fields make the future 1,000-pair and six-category trigger countable. They
do not claim that the trigger has been reached.

### Leakage backstop

`content/tools/leakage_check.py` recursively scans every `*.jsonl` under
`content/run/foundry/`. It uses `preference.scan_jsonl` to validate each
record's schema and required fields. The recursive marker scan covers every key
and value, including slot metadata, panel evidence, choices, and source
references. It rejects boundary-delimited identifier and path forms for gold,
held-out, ETS, Tier 3, GR9677, and GR1777 while allowing benign words such as
`marigold`. Errors include the JSON path and line number. The leakage tool also
retains the forbidden private-root checks and the 25-word contiguous copy-in
check against available private items. These checks supplement the primary
firewall: generation and preference pairing ground only on `content/corpus/`.

The same check runs a cross-run audit over every nested `preferences.jsonl`.
Duplicate chosen and rejected identities across files fail. For each
non-synthetic pair, both source references must exactly match a `source_ref` in
the corpus index. Preference files with no available index fail source
verification clearly. Synthetic source references may remain synthetic, but
they are excluded from the audit's Tier 3 pair and category counts. The audit
reports validated non-synthetic count, sorted eligible categories, duplicates,
errors, and `tier3_ready`; readiness requires at least 1,000 eligible pairs,
at least six categories, and no duplicate or validation error.

### Standing verifier evaluation

`content/tools/eval_verifier.py`, run with `just eval-verifier`, reads saved
predictions and labels without constructing a model client or making a network
call. Its input requires distinct calibration and held-out splits:

```json
{
    "calibration": {
        "properties": {
            "key": {
                "item_ids": ["cal-key-001", "cal-key-002"],
                "predicted": [true, false],
                "human": [true, false],
                "confidence": [0.9, 0.7],
                "runs": [[true, false], [true, false]]
            }
        }
    },
    "heldout": {
        "properties": {
            "key": {
                "item_ids": ["heldout-key-101", "heldout-key-102"],
                "predicted": [true, false],
                "human": [true, false],
                "confidence": [0.95, 0.6],
                "runs": [[true, false], [true, false]]
            }
        }
    }
}
```

`item_ids`, `predicted`, and `human` are required aligned arrays. Item IDs are
non-empty unique opaque strings, not item text. Any overlap between the union of
calibration IDs and the union of held-out IDs is invalid, even when the overlap
occurs under different property names. `confidence` is an optional aligned
array of values from 0 to 1. `runs` is optional; when present, it contains at
least two aligned boolean arrays from perturbation runs. Consistency compares
the original `predicted` verdicts and every perturbation run. Without `runs`,
consistency is `null` and its gate is red.

Only calibration predicted positives and their human labels can fit a
threshold. Each threshold reports `target_precision`, `attainable`, `cutoff`,
`achieved_precision`, `retained`, and `eligible`. An unattainable 0.95 target
has a null cutoff and fails closed. The fixed calibration cutoff is then applied
to held-out predicted positives with aligned confidence. Pre-threshold
agreement, balanced accuracy, precision, and recall remain diagnostics.
Headline held-out metrics and gates use the post-threshold predictions, so a
high cutoff's recall and balanced-accuracy loss remain visible. Changing
held-out labels or confidences cannot change the fitted cutoff.

The held-out split accepts only opaque IDs, labels, confidence, and perturbation
arrays shown above. It contains no stems, choices, source text, or other item
content. These values are evaluation-only. They never enter a prompt,
generation context, or preference pair.

The standing gate is green only when all checks have evidence:

- key and figure exist in both splits;
- every required property has at least 30 aligned examples, five human
  positives, and five human negatives in each split;
- post-threshold held-out raw agreement is at least 0.90 and balanced accuracy
  is at least 0.85 for every reported property;
- the calibration precision target is attainable for every reported property;
- key and figure each retain at least 20 held-out accepts, with accepted
  precision point and bootstrap lower bound both at least 0.95;
- held-out consistency is measured over at least 30 items and is at least 0.90
  for every property;
- a per-slot foundry summary has at least six non-empty slots across at least
  six locked categories;
- foundry escalation point and slot-bootstrap upper bound are both no greater
  than 0.15.

Each gate check reports `observed`, `required`, `pass`, `support`, and
`evidence`. Missing support is red.
Structurally valid red evaluations are still printed and written, then the
command exits 1. Invalid inputs exit 2. A green evaluation exits 0.

Run `just eval-verifier` with `--labels <labels.json>` and
`--foundry-summary <summary.json-or-foundry-root>`. A file supplies one legacy
or explicit multi-slot payload. A directory recursively loads each
`<run>/summary.json` and builds the production multi-slot aggregate. Add
`--preferences-root <foundry-root>` for non-synthetic Tier 3 counts and
cross-run duplicate visibility. Add `--out <path>` to save the identical
printed report. `just eval-verifier --self-check` uses realistically supported
synthetic calibration, held-out, and six-slot foundry data and exits 0.

For cluster-aware foundry uncertainty, supply per-slot counts:

```json
{
    "slots": [
        {
            "blueprint_category": "mechanics",
            "accepted": 18,
            "rejected": 1,
            "escalated": 1
        },
        {
            "blueprint_category": "optics_waves",
            "accepted": 17,
            "rejected": 2,
            "escalated": 1
        }
    ]
}
```

Yield and escalation intervals bootstrap non-empty slot rates through the
existing `eval_metrics.bootstrap_ci`. The headline rates are the unweighted
means of those same slot rates and exactly equal each interval's `point`.
Candidate-weighted diagnostics are named `pooled_yield_rate` and
`pooled_escalation_rate`. Zero-candidate slots remain in the report but not in
rate or interval samples. Reports identify `ci_unit` as `slot` and include the
valid non-empty category count. Fewer than two non-empty slots produce null
intervals; fewer than six non-empty slots or six categories is a red support
gate. A legacy single aggregate still reports point rates, but its intervals
and `ci_unit` are null. Zero-candidate legacy rates are null.

### Future Tier gates

These gates are prerequisites for future training, not evidence that training
has begun:

- **Tier 2, distilled verifier:** calibration-card accept-precision at or above
  `0.95` on key and figure, plus at least `300` panel-labeled problems under
  `content/run/foundry/`. Because that tree is git-ignored, an operator verifies
  the count.
- **Tier 3, SFT then optional DPO:** at least `1000` validated non-synthetic
  preference pairs across at least `6` locked blueprint categories, no
  cross-run duplicates or audit errors, a clean leakage check, and a green
  Phase 3 standing eval on the latest calibration card.

The human calibration set is not complete, neither numeric count has been
reached, and no Tier 2 or Tier 3 training has started.

---

## Commands

| Command                      | What it does                                                                                                       |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `assemble_bundle.py`         | The single gated landing command: land, convert math, wire figures, run invariants.                                |
| `just test-py`               | Runs the Python tests, including the content-bundle invariant gate (per-commit).                                   |
| `just audit-bundle-ai`       | Runs the five on-demand AI audits (pre-release or nightly, needs the AI runtime).                                  |
| `just foundry-dry`           | Offline foundry smoke (`foundry.py --self-check`), no network.                                                     |
| `just foundry`               | Best-of-N foundry loop; needs AI runtime + key when online generation is enabled.                                  |
| `foundry.py`                 | Sample, cap N by verifier accuracy, and write four JSON files plus `preferences.jsonl` under each run directory.   |
| `make_foundry_escalation.py` | Build a human review sheet from the latest run's `escalated.json` (or `--run <name>`).                             |
| `calibrate_verifier.py`      | Offline smoke (`--self-check`) of the calibration stats and card assembly.                                         |
| `leakage_check.py`           | Recursively validate foundry preference schema, private-root markers, and private-item copy-in.                    |
| `just eval-verifier`         | Fit calibration-only thresholds, score held-out labels, apply standing gates, and report slot-clustered intervals. |
| `just check`                 | The overall gate (format, build, lint, all tests), which includes `test-py`.                                       |

The LLM audits and the foundry loop need the optional AI runtime and a key when
they call models; install it once with `just pgrep-ai-deps` and set
`OPENAI_API_KEY` (or add it to `content/.env`). `just foundry-dry`, `--dry-run`,
`just eval-verifier`, and the deterministic audits run without a key.
