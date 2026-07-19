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

## One OpenAI-compatible LLM seam

`pylib/anki/pgrep/ai/llm.py` `LLMClient` is the single seam for
OpenAI-compatible app and content calls outside the quarantined shadow runner.
It pins an exact dated model snapshot (it refuses a floating alias), uses a low
temperature and a seed when the snapshot supports one, retries transient errors
with a short backoff, and drops any option a snapshot rejects so the strongest
model still works. Its two public methods are `complete_text(system, user, *,
json_object=False)` for a raw completion and `complete_json(...)` for a parsed
JSON object. `load_api_key(...)` is the one place that resolves credentials for
that seam: the TrueFoundry gateway file
`~/.config/truefoundry/gateway.env` (one token + `OPENAI_BASE_URL`), then an
explicit `env_file`, then optional non-secret `content/.env` / repo-root `.env`
fallbacks. Direct provider keys must not live in the repo. `openai` is imported
lazily, so an AI-off app never loads it.

Quarantined shadow calls instead use the provider-neutral `ModelBackend`
protocol through `shadow_foundry.py`'s recording backend. At their respective
protected boundaries, `LLMClient` attaches to the run manager when
`PGREP_BATCH_RUN_DIR` is present, while the shadow runner passes that manager
around its backend calls. Both paths therefore honor the same per-run permits
when invoked by a protected recipe without pretending that all model calls use
one client.

The figure generator (`tools/pgrep_figure_gen.py`), the figure judge
(`tools/pgrep_figure_verify.py`), and the technique-giveaway judge
(`content/tools/check_technique_giveaway.py`) all route through this client
instead of each holding a private OpenAI client and retry loop.

---

## Generation circuit breaker (operator controls)

The lightweight circuit breaker protects only high-volume online generation,
not every use of an LLM client. Before `just shadow-foundry`, future online
`just foundry`, `just gen-decompositions`, or an LLM-backed
`just audit-bundle-ai` selection can start, the operator must choose every
positive limit explicitly:

| Limit                      | Environment variable          |
| -------------------------- | ----------------------------- |
| Provider calls             | `PGREP_BATCH_MAX_CALLS`       |
| Concurrent provider calls  | `PGREP_BATCH_MAX_CONCURRENCY` |
| Cumulative retries per run | `PGREP_BATCH_MAX_RETRIES`     |
| Elapsed minutes            | `PGREP_BATCH_MAX_MINUTES`     |

There are no limit defaults. Set the variables in the shell or, optionally, in
the ignored `content/run/batch-safety.env`, which protected recipes load before
preflight. Set `PGREP_BATCH_SAFETY_ENV_FILE` to use a different config path;
leaving it unset preserves the documented default. Missing, non-positive,
malformed, unreadable, or corrupt safety state fails closed before another
provider call.

`just foundry --self-check`, `just foundry --dry-run`, `just foundry-dry`, and
`just shadow-smoke` are offline and unprotected; they make no provider calls.
So is `just audit-bundle-ai --only decomposition_leak citation` when
`--include-variant-solve` is absent. The audit tool's own argument parser and
selection rules classify that path. The default audit selection, any selected
LLM audit, and decomposition leak with variant re-solve remain protected. The
circuit breaker does not wrap unrelated tools or act as a global paid-call
checker.

Each protected run gets a private `safety.json`. It is a sidecar in the run's
safety directory while output is atomically published; finalized shadow and
foundry artifact directories receive a copy beside their published files.
The stable, privacy-safe fields are `run_id`, `tool`, `status`, `limits`,
`counters`, `started_at`, `updated_at`, and `stop_reason`. Limits contain the
four selected ceilings. Counters contain started, completed, failed, active,
peak-concurrency, and retry counts. They never contain prompts, completions,
credentials, tokens, prices, or account information.

The protected wrapper prints a stable status line and starts a terminal watcher.
Use `just generation-status` for the latest state below `content/run`, or pass
`--run-dir <dir>` for one state. The line reports calls, active calls, retries,
elapsed time, lifecycle state (`RUNNING`, `COMPLETED`, `FAILED`, or `STOPPED`),
and a stop reason. A running state's elapsed time advances against the current
time; terminal elapsed time is frozen at `updated_at`.

`just generation-stop` creates the global `content/run/STOP_GENERATION`.
Protected runs stop before their next provider call and, when state remains
writable, persist `STOPPED` with `KILL_SWITCH`. `just generation-resume` removes
only that file: it does not revive a stopped run. Start a new protected run
after examining its terminal `safety.json`. Call, concurrency, retry, and
duration stops likewise persist a terminal state when the state update
succeeds.

A state-I/O problem always fails closed. When the existing state can still be
read and written, the manager records `STOPPED` with `STATE_IO`; lock, read, or
write corruption may instead leave the prior state or an unreadable file
because the failure itself prevents that update. Terminal command output
reports the state-I/O failure in either case. An unlocked active-call permit is
evidence that its worker crashed. Attach and terminal finalization persist
`STOPPED/STATE_IO` when possible and raise; they never reclaim that permit and
continue or leave a readable run permanently `RUNNING`.

On normal finalization, the wrapper marks a successful command `COMPLETED` and
a tool error `FAILED`; a persisted circuit-breaker denial remains `STOPPED`. If
the tool swallowed a denial but returned zero, `batch_manager finish` still
returns nonzero for the stopped state and the wrapper fails closed. An already
nonzero tool status remains the wrapper's exit status. If state I/O prevents
the terminal update, the command fails and reports that error rather than
presenting the artifact as safely finalized. A failed atomic publication has
no finalized output directory or success marker, so it cannot be mistaken for
a completed artifact.

Non-goals: no token/USD or daily accounting, pricing or model policy, usage
reports, legacy-bypass cleanup, global paid-call interception, or network
smoke. This is bounded-call safety, not billing.

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
and a Markdown summary under `content/run/audit/`. Selecting only the two
deterministic audits runs directly without generation limits; adding
`--include-variant-solve`, selecting any LLM audit, or using the default
selection routes through the protected wrapper.

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
directory. It writes `_SUCCESS` in the temporary directory immediately before
the rename; only the renamed directory with that marker is finalized. An
exclusive sibling lock file closes the final check and rename race; lock and
temporary state are removed on success or failure. Timestamp run IDs include
microseconds. Default artifacts stay under the ignored
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
`failing_gates` must exactly match its failed hard-check names. A non-synthetic
chosen item needs at least one check and cannot contain a failed hard check.
Successful checks may legitimately have empty evidence, matching the real
`PanelVerdict` contract. Synthetic chosen items may have no checks.
Recursive validation permits only JSON-compatible values and string object
keys; sets, tuples, object instances, NaN, and infinities fail before
serialization. Invalid construction or writing raises `ValueError`; no record
is silently skipped.

The locked category vocabulary is `mechanics`, `electromagnetism`, `quantum`,
`thermodynamics`, `atomic`, `optics_waves`, `special_relativity`, `lab`, and
`specialized`. Case, whitespace, spelling, and separator variants are rejected
rather than normalized.

Only validated accepted by rejected combinations from the same slot become
pairs, capped at 64 per call. Escalations and slots lacking either side produce
no pair. Rejected items with `panel.refusal: true` are explicitly excluded and
counted because they are incomplete generation outcomes, not negative training
examples. Any other malformed accepted or rejected training candidate raises an
actionable `ValueError`, aborts publication, and leaves no final directory or
`_SUCCESS` marker. A non-positive cap produces zero pairs.

`content/tools/foundry.py` atomically overwrites one new run's
`preferences.jsonl`; it never appends to an earlier run. Duplicate chosen and
rejected ID combinations fail the write. Every pair has an explicit
`synthetic` boolean. Dry-run pairs are synthetic and can exercise the pipeline,
but they never count toward training readiness. `summary.json` includes its
`blueprint_category`, a run-level `synthetic` flag, and a
`preference_summary` object. That object reports emitted pairs, excluded
outcomes, exclusion reasons such as `panel_refusal`, total validated count,
non-synthetic pair count, distinct eligible category count, and category names.
These fields make the future 1,000-pair and six-category trigger countable. They
do not claim that the trigger has been reached.

### Leakage backstop

`content/tools/leakage_check.py` recursively scans each finalized run's
`preferences.jsonl` under `content/run/foundry/`. A finalized run has `_SUCCESS`
and is not a temporary hidden directory. Active temporary directories, lock
files, orphan directories, and bare files under the root are ignored. The
recursive marker scan covers every key and value, including slot metadata,
panel evidence, choices, and source references. It rejects boundary-delimited
identifier and path forms for gold, `heldout`, `held-out`, `held_out`, ETS,
Tier 3 separator variants, GR9677, and GR1777 while allowing benign words such
as `marigold`. Errors include the JSON path and line number. The leakage tool
also retains the forbidden private-root checks and the 25-word contiguous
copy-in check against available private items. These checks supplement the
primary firewall: generation and preference pairing ground only on
`content/corpus/`.

The same check runs a cross-run audit over every nested `preferences.jsonl`.
Duplicate chosen and rejected identities across files fail. For each
non-synthetic pair, both source references must exactly match a `source_ref` in
the corpus index. Preference files with no available index fail source
verification clearly. Synthetic source references may remain synthetic, but
they are excluded from the audit's Tier 3 pair and category counts. The audit
reports validated non-synthetic count, sorted eligible categories, duplicates,
errors, and `tier3_ready`; readiness requires at least 1,000 eligible pairs,
at least six categories, and no duplicate or validation error.

Every synthetic row is still structurally validated, but synthetic rows are
filtered before production identities, duplicates, categories, counts, and
Tier-readiness errors are built. Synthetic validation findings and exclusion
counts remain diagnostics. Repeated finalized dry runs with identical dry IDs
therefore cannot create a production duplicate or fail the leakage gate.

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
non-empty unique opaque strings, not item text. They must be stable hashes or
stable IDs from a frozen evaluation manifest; per-run row numbers do not make
overlap detection meaningful. Any overlap between the union of calibration IDs
and the union of held-out IDs is invalid, even when the overlap occurs under
different property names. `confidence` is an optional aligned array of values
from 0 to 1. `runs` is optional; when present, it contains at least two aligned
boolean arrays from perturbation runs. Consistency compares the original
`predicted` verdicts and every perturbation run. Without `runs`, consistency is
`null` and its gate is red.

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
  precision point, percentile-bootstrap lower bound, and deterministic 95%
  Wilson lower bound all at least 0.95;
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
in-memory calibration and held-out data with 110 all-correct retained accepts,
plus six-slot foundry data, and exits 0.

Directory aggregation includes only finalized `_SUCCESS` runs. It ignores
active temporary, lock, orphan, and bare-root artifacts. Finalized synthetic
runs are reported as excluded and do not enter production slot rates. The
cross-run preference audit applies the same finalized-run boundary and reports
the number of synthetic pairs excluded from Tier counts.

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

## The shadow foundry (Phase 4)

Phase 4 adds real multi-model generation in a quarantine-only shadow mode. It
runs the exact frontier portfolio and prompts intended for future production,
but every output is quarantined. Nothing it produces can enter
`content_bundle.json` or `preferences.jsonl`. The design is
[`shadow-foundry-calibration-design.md`](../plan/shadow-foundry-calibration-design.md)
and the runner plan is
[`multi-model-shadow-runner-plan.md`](../plan/multi-model-shadow-runner-plan.md).

The seam is provider-neutral: `pylib/anki/pgrep/ai/model_backend.py` defines
`ModelSpec`, `ModelRequest`, `ModelResult`, and the `ModelBackend` protocol, and
`pylib/anki/pgrep/ai/shadow_portfolio.py` holds the pure allocation, strict
candidate parsing, and origin-excluding cross-verification. `content/tools/`
holds `shadow_foundry.py` (the CLI, corpus retrieval, model probe, firewall
checks, and atomic publication). The shipped online backend is
`pylib/anki/pgrep/ai/truefoundry_backend.py`.

### TrueFoundry gateway runtime

Real shadow probes and completions use the OpenAI-compatible TrueFoundry gateway
directly. Credentials come only from
`~/.config/truefoundry/gateway.env`: `OPENAI_API_KEY` is the TrueFoundry token
and `OPENAI_BASE_URL` is the gateway URL. Ambient direct-provider values and
repository/content `.env` files are not fallback sources. The backend imports
the OpenAI client lazily, preserves exact gateway model IDs, and records only
sanitized exception class/status context.

### Exact model probe and required IDs

The backend calls the gateway model-list endpoint and returns exact accessible
IDs. The host normalizes this into a probe object with `models`, the actual
OpenAI Python package `sdk_version`, `probed_at`, and a `model_catalog_hash`.

`just shadow-models` runs only the probe. It prints a human-readable list and
the strict JSON, and generates nothing. Gateway generation requires three
exact, distinct, account-listed IDs assigned explicitly to the Sol, Opus, and
Grok portfolio roles.

`validate_exact_roles` requires that each requested ID is present in the account
probe and that the three IDs are distinct. Provider prefixes, deployment names,
versions, and unconventional IDs are preserved without parsing or inference.
If a requested exact model is missing, the run fails before the first candidate
call and does not substitute another model.

### Quarantine root and artifacts

Every run is written under the git-ignored quarantine root
`content/run/shadow-foundry/<run-id>/`. Each run directory contains exactly:

- `manifest.json`, the strict run manifest;
- `candidates.json`, the quarantined candidates with their generation and
  cross-verification traces;
- `failures.json`, the recorded failures and reasons;
- one marker, `_SUCCESS` for a complete portfolio or `_FAILED` for a diagnostic
  (partial or preflight failure) run.

Publication is atomic. An exclusive sibling lock, a temporary sibling directory,
strict JSON, and hard-link finalization mean the marker is written last. An
interrupted run leaves no marker, and downstream readers ignore any directory
without one. Diagnostic `_FAILED` runs are preserved for inspection. Raw
transcripts stay under the run directory; API keys and authorization headers are
never written, and captured errors are redacted.

### Gateway runtime and replay manifest

The manifest (`manifest_version` `pgrep-shadow-run/v7`) binds the run to the
exact code, gateway runtime, corpus, and model state so a success is replayable:

- `runtime.backend_kind` (`truefoundry-openai-compatible`),
  `runtime.execution_mode` (`gateway`), and the actual
  `runtime.openai_sdk_version`;
- `code.sha` and `code.tree_status`, with `replayable` true only for a success
  produced from a clean tree;
- `corpus_index` fingerprint, `mtime_ns`, and size;
- `probe`, the full account catalog plus `sdk_version` and `model_catalog_hash`;
- `roles`, `allocation`, `seeds`, and `choice_permutations`;
- `prompt_versions`, `schema_versions`, and per-candidate `request_traces` with
  request hashes;
- each request trace and quarantined raw response binds the exact backend kind,
  `agent_id`, provider response `run_id`, requested/actual model IDs, and request
  hash.

### No acceptance, pairs, or landing

Shadow mode has no path to acceptance, preference pairs, or bundle landing. The
manifest records `training_eligible: false` and an `artifacts` block with
`accepted_json`, `preferences_jsonl`, `bundle_mutation`, and `assemble_call` all
false. Cross-verification only records the two non-origin families' blind solve
opinions; it never accepts or rejects. There is no arrow from a shadow run to
`assemble_bundle.py` or `preferences.jsonl`, and no command-line flag changes
this. Building the human calibration ruler and any unlock decision are separate,
later work (`blind-calibration-ruler-plan.md`).

### Offline smoke

`just shadow-smoke` runs `shadow_foundry.py --self-check`: a fully offline
fake-client portfolio with no network and no key. It exercises
allocation, parsing, cross-verification, manifest assembly, and atomic
publication into the real quarantine root, then reports the run directory. This
is the per-commit-safe check; the account probe and any real run are on-demand.

### Troubleshooting

- `TrueFoundry gateway environment file is unavailable`: create the external
  gateway file with nonempty `OPENAI_API_KEY` and `OPENAI_BASE_URL`.
- `exact model <id> ... is not in the account probe`: run
  `just shadow-models`, assign three distinct exact listed IDs, and never
  substitute.
- A `_FAILED` run directory: read its `manifest.json` and `failures.json`. A
  gateway preflight failure records the redacted reason without touching the
  corpus.

### Blind calibration ruler: offline operator handoff

The blind ruler is a private, offline human-label workflow for a _finalized
real_ shadow run. It is not a way to make a synthetic ruler, run models, fit a
threshold, unlock acceptance, emit preferences, or mutate the shipped bundle.
Do not run a real shadow portfolio just to exercise this handoff.

Real paid shadow generation uses the external TrueFoundry gateway and explicit
circuit-breaker limits. The exact private workflow is:

1. Probe the calling account and capture the exact listed model ID for each
   family:

   ```bash
   just shadow-models
   ```

2. Use those exact account-listed IDs for the paid real shadow run:

   ```bash
   just shadow-foundry \
     --sol-model <exact-sol-id> \
     --opus-model <exact-opus-id> \
     --grok-model <exact-grok-id> \
     --n 40 \
     --seed 8 \
     --run <shadow-run-id>
   ```

   `--topic` is optional in the current CLI; when omitted as above it uses
   `mechanics/circular-motion`. The run must finish as a finalized,
   three-family `_SUCCESS` directory under
   `content/run/shadow-foundry/<shadow-run-id>/`. A smoke, synthetic, partial,
   dirty, `_FAILED`, non-replayable, or non-three-family run cannot build a
   production ruler.
3. Select existing private inputs that satisfy the builder's production path
   and data-firewall contracts. Trusted, failure, and shadow material must
   exclude gold, held-out, ETS, Tier-3, and all other private evaluation
   material. Shadow generation uses only the allowed corpus; trusted/failure
   inputs come only from allowed corpus-backed, audit, or rejected content.
   The builder fails closed on forbidden dataset markers in trusted/failure
   paths or recursive content, while the finalized shadow contract retains the
   generation firewall.

   The trusted and failure JSON files must both be regular files beneath the
   git-ignored `content/run/` root. The shadow input must be either the finalized
   run directory beneath `content/run/shadow-foundry/` or that directory's exact
   `candidates.json` path. The directory form is shown here:

   ```bash
   just calibration-ruler \
     --trusted content/run/<trusted-input>.json \
     --failures content/run/<failure-input>.json \
     --shadow content/run/shadow-foundry/<shadow-run-id> \
     --run <calibration-run-id> \
     --seed 7
   ```

   Angle-bracket names in these commands are metavariables, not files supplied
   by the repository. Replace them with the exact probed IDs and existing
   private paths/run IDs. Production output is fixed at the exact git-ignored
   `content/run/calibration/<calibration-run-id>/` path; a custom output root is
   rejected. The two seeds intentionally differ: shadow seed 8 gives the extra
   40th generated candidate to Opus (`14 Opus / 13 Sol / 13 Grok`), matching
   the ruler seed-7 requirement. Shadow seed 7 would give Sol 14 and leave the
   seed-7 ruler without its required 14 Opus candidates.
   Every trusted/failure item selected into the ruler must carry a non-empty
   `source_excerpt`; every shadow candidate must carry bound provenance with a
   non-empty `quote_anchor`. The private builder preserves selected excerpts in
   the hidden manifest and refuses publication if any selected item lacks one.
   Pass A never renders them; Pass B hashes and renders the exact protected
   excerpts.
   The builder CLI prints only `CALIBRATION_BUILD_COMPLETE` on success.
   Failures use `CALIBRATION_BUILD_ERROR:<safe-category>` and do not print raw
   exceptions, rejected values, private paths/content, or hashes.
4. Inspect the generated private workspace
   `content/run/calibration/<calibration-run-id>/`. Complete labels only in the exact
   `pass-a/block-*.md` files. `index.md` and `figures/<review-id>.svg` are
   review assets, not editable inputs: do not rename, replace, or edit them.
5. Import Pass A:

   ```bash
   just calibration-import-a <calibration-run-id>
   ```

6. Only when the resulting Pass A report has status `PASS_A_COMPLETE`, complete
   the generated exact `pass-b/block-*.md` files.
7. Import Pass B:

   ```bash
   just calibration-import-b <calibration-run-id>
   ```

The import CLIs print only status, the private report path, label count, and
Pass A repeat-consistency counts. They never print labels, notes, excerpts,
manifest/report hashes, or hidden item metadata.
CLI failures use only stable `CALIBRATION_IMPORT_ERROR:<safe-category>` codes
such as `reviewer_field`, `workspace_schema`, or `filesystem_state`; raw
exceptions, malformed lines, reviewer values, hashes, excerpts, decomposition
text, and unsafe filesystem paths are never printed.

The 120-item ruler has 12 hidden repeats. Pass A requires at least 11 of 12
matching `your_answer` labels and raw agreement of at least 0.90 for every
other categorical field. A miss returns `ADJUDICATION_REQUIRED`, writes the
private `reports/pass-a-labels.json`, and does not generate Pass B. That state
is immutable and terminal for the run: preserve the failed workspace and
report, never delete or overwrite the evidence, and do not open or attempt Pass
B. Adjudicate outside the immutable workspace, build a fresh ruler under a new
calibration run ID, and repeat Pass A there. The importer refuses a second Pass
A import once the report exists and does not waive or tune the predeclared
floors.

Pass A fields are:

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

Pass B is withheld until successful Pass A import. It exposes the protected
source excerpt and canonical decomposition for the same opaque IDs and uses
only:

```text
source_supports_stem: PASS | FAIL | UNSURE
source_supports_answer: PASS | FAIL | UNSURE
decomposition_correct: PASS | FAIL | UNSURE
decomposition_leaks_answer: PASS | FAIL | UNSURE
notes:
```

For both passes, work independently without AI assistance. A calculator and
scratch work are allowed; use `UNSURE` rather than guessing. Do not infer model
identity, and never change headings, review IDs, item order, rubric field
names, protected visible text, figure assets, index, or block filenames.
`notes` must be a single ordinary-Unicode line, at most 2,000 characters.
The parser rejects missing/extra/unknown fields, changed assets or text,
symlinks and path escapes, unexpected files, incomplete blocks, and any
non-exact layout. It also keeps model identity, answers, verifier output,
recommendations, split assignment, provenance, and repeat bindings out of the
blind review surfaces.

Successful imports atomically publish only private fixed-shape reports:

- `reports/pass-a-labels.json`, status `PASS_A_COMPLETE`, and generated
  `pass-b/block-*.md` plus `pass-b/_SUCCESS`;
- `reports/pass-b-labels.json`, status `PASS_B_COMPLETE`.

Treat those paths and statuses as the handoff result. Until human labels
complete and import successfully, the post-label evaluator, threshold fit,
unlock controller, acceptance, preference emission, and bundle landing remain
blocked. Even a complete Pass B does not itself perform any of those actions.

The importer retains suspicious or rolled-back private state rather than
deleting it. Rollback preservation lives at
`content/run/calibration/.calibration-rollback-quarantine/`; every import also
retains a fresh same-filesystem rename-capability probe at
`content/run/calibration/.capability-probes/`. These mode-0700 areas preserve
transaction/probe evidence and avoid foreign-data races. The importer never
auto-deletes or consumes them. An operator may inspect and clean them only when
no import is active and every retained identity is understood. Do not expose
their contents, label data, manifests, excerpts, or hashes in logs; failures
report only the private path and retained-entry count.

The ruler builder opens every input component and file with retained
descriptors and `O_NOFOLLOW`, retains the exact input bytes and identities
through final attestation, and performs publication writes and verification
relative to retained output-root/run descriptors. Rollback moves locks,
foreign replacements, and uniquely located owned trees with atomic
rename-no-replace into the private mode-0700
`content/run/calibration/.calibration-build-quarantine/`; it does not delete or
overwrite those bindings. `_SUCCESS` is written through the retained run
descriptor only after final root/run/input/source and exact-workspace
attestation. After the marker is fsynced, the builder rechecks every exact root,
Pass A, and figure entry plus every payload identity and byte sequence before
returning success. Every build first retains a real same-filesystem
rename-no-replace move/collision probe under the private mode-0700
`content/run/calibration/.calibration-build-probes/`; probe artifacts are
operator-cleaned and are never consumed as ruler input.

---

## Commands

| Command                      | What it does                                                                                                           |
| ---------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `assemble_bundle.py`         | The single gated landing command: land, convert math, wire figures, run invariants.                                    |
| `just test-py`               | Runs the Python tests, including the content-bundle invariant gate (per-commit).                                       |
| `just audit-bundle-ai`       | Runs selected on-demand audits; deterministic-only mode bypasses generation limits, while every LLM mode is protected. |
| `just foundry-dry`           | Offline foundry smoke (`foundry.py --self-check`), no network.                                                         |
| `just foundry`               | Best-of-N foundry loop; online use requires AI runtime, key, and explicit circuit-breaker limits.                      |
| `foundry.py`                 | Sample, cap N by verifier accuracy, and write four JSON files plus `preferences.jsonl` under each run directory.       |
| `make_foundry_escalation.py` | Build a human review sheet from the latest run's `escalated.json` (or `--run <name>`).                                 |
| `calibrate_verifier.py`      | Offline smoke (`--self-check`) of the calibration stats and card assembly.                                             |
| `leakage_check.py`           | Recursively validate foundry preference schema, private-root markers, and private-item copy-in.                        |
| `just eval-verifier`         | Fit calibration-only thresholds, score held-out labels, apply standing gates, and report slot-clustered intervals.     |
| `just shadow-smoke`          | Offline fake-client shadow portfolio (`shadow_foundry.py --self-check`), no network or key.                            |
| `just shadow-models`         | Probe exact IDs through the external TrueFoundry OpenAI-compatible gateway.                                            |
| `just shadow-worker-build`   | Legacy developer utility for the retained isolated-worker tests; not used by the gateway production path.              |
| `just shadow-worker-sync`    | Legacy developer utility for the retained isolated-worker tests; not used by the gateway production path.              |
| `just shadow-foundry`        | Quarantined multi-model generation with exact model IDs and explicit circuit-breaker limits; never lands or pairs.     |
| `just calibration-ruler`     | Build a private blind ruler and Pass A Markdown from trusted, failure, and finalized real shadow inputs.               |
| `just calibration-import-a`  | Strictly import one completed private Pass A; may generate Pass B on `PASS_A_COMPLETE`.                                |
| `just calibration-import-b`  | Strictly import one completed private Pass B after a successful immutable Pass A report.                               |
| `just generation-status`     | Print the latest safety state, or pass `--run-dir <dir>` for a specific protected run.                                 |
| `just generation-stop`       | Create the global stop file; protected runs stop before their next provider call.                                      |
| `just generation-resume`     | Remove the global stop file; terminal runs remain terminal.                                                            |
| `just check`                 | The overall gate (format, build, lint, all tests), which includes `test-py`.                                           |

The LLM audits and the foundry loop need the optional AI runtime and a key when
they call models; install it once with `just ai-deps` and set
`OPENAI_API_KEY` (or add it to `content/.env`). Protected online work also
requires the four explicit generation limits above. `just foundry-dry`,
`--dry-run`, `just eval-verifier`, and deterministic-only audits without
variant re-solve run without a key or circuit-breaker limits.

The shadow foundry is separate. `just shadow-smoke` runs fully offline.
`just shadow-models` and `just shadow-foundry` use only the external
TrueFoundry gateway file. The retained worker commands are developer utilities
and are not part of real shadow execution or manifest provenance.
