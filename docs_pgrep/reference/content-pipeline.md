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
JSON object. `load_api_key(...)` is the one place that resolves credentials: the
TrueFoundry gateway file `~/.config/truefoundry/gateway.env` (one token +
`OPENAI_BASE_URL`), then an explicit `env_file`, then optional non-secret
`content/.env` / repo-root `.env` fallbacks. Direct provider keys must not live
in the repo. `openai` is imported lazily, so an AI-off app never loads it.

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
holds the two host-side tools: `cursor_sandbox.py` (the Docker adapter) and
`shadow_foundry.py` (the CLI, corpus retrieval, model probe, firewall checks,
and atomic publication).

### Docker-only local Unix socket

The Cursor SDK call runs inside a disposable local Docker container, one prompt
per container. This first implementation is Docker-only. `detect_runtime`
returns Docker or raises, and `discover_local_runtime` accepts only a verified,
allowlisted local Unix socket: on macOS `~/.docker/run/docker.sock` or
`/var/run/docker.sock`, on Linux `/var/run/docker.sock`, `/run/docker.sock`, or
`/run/user/<uid>/docker.sock`. Remote endpoints (`ssh://`, `tcp://`, `http://`,
`https://`, `npipe://`, or an explicit `unix://` URL) are rejected, the socket
must not be a symlink, and it must be a real socket owned by root or the calling
user. Podman and any other runtime are not supported. If no verified local
Docker socket is available, or the per-request mount boundary cannot be proven,
the run fails before the first prompt. There is no non-Docker fallback: an
unavailable engine is a hard stop, not a reason to run a model on the host.

Each container is hardened: only the freshly created request directory is bound
to `/work`, the API key is forwarded by name (`--env CURSOR_API_KEY`, never as
an argument or in `request.json`), and the container runs read-only with
`--cap-drop ALL`, `no-new-privileges`, a pids limit, memory and CPU caps, and a
`noexec` tmpfs. No repository checkout, parent path, HOME, Docker socket, MCP
server, ambient setting source, or other host credential is exposed. Before the
worker runs, a keyless two-way mount-nonce probe proves that the container sees
exactly that request directory and nothing else. Symlinks, hard links, path
escapes, and private training-data markers (gold, held-out, ETS, GR9677,
GR1777, Tier 3) are rejected before any container spawns, and every captured
error is redacted.

### Worker build and sync

The isolated worker lives under `tools/shadow_worker/` (`Dockerfile`,
`pyproject.toml`, `uv.lock`, `worker.py`) and depends only on `cursor-sdk` in
its own locked environment. `worker.py` reads `/work/request.json`, writes
`/work/result.json`, and supports only the `models` and `prompt` actions; it
imports `cursor_sdk` lazily so root CI can load the protocol without the SDK.

- `just shadow-worker-sync` installs the worker's locked environment into
  `out/shadow-worker-venv` without creating a nested project virtualenv. It does
  not build an image and needs no Docker daemon.
- `just shadow-worker-build` builds the pinned Docker image and prints its
  immutable `sha256:` digest. It needs a running local Docker engine.

The runner does not rely on a floating image tag. `prepare_real_sandbox` builds
the image from the whitelisted `tools/shadow_worker/` context, inspects its
immutable digest, and rebinds the sandbox to that exact digest, so the model
call, the mount probe, and the manifest all reference one immutable image. The
image tag itself is derived from a fingerprint of the worker context files
(`pgrep-shadow-worker:<hash>`).

### Exact model probe and required IDs

The runner never assumes a display name is a callable model. Inside the sandbox,
the worker calls `Cursor.models.list()` and returns the account catalog with its
per-model `parameters` and `variants` plus the actual `cursor-sdk` version. The
host normalizes this into a probe object with `models`, `sdk_version`,
`probed_at`, and a `model_catalog_hash`.

`just shadow-models` runs only the probe. It prints a human-readable list and
the strict JSON, and generates nothing. Real generation requires three exact,
distinct, account-listed IDs, one per family. The shipped defaults, and the IDs
`shadow-models` must show, are:

| Family | Required model ID                    |
| ------ | ------------------------------------ |
| Sol    | `gpt-5.6-sol-max`                    |
| Opus   | `claude-opus-4-8-thinking-high-fast` |
| Grok   | `cursor-grok-4.5-high-fast`          |

`validate_exact_roles` requires that each requested ID is present in the account
probe, that the three IDs are distinct, and that each ID matches its family
identity (a Sol ID must read as GPT 5.6 Sol, an Opus ID as Claude Opus 4.8, a
Grok ID as Grok 4.5). `auto` and any `auto/...` alias are forbidden. If a
requested family's exact model is missing or renamed, the run fails before the
first candidate call and does not substitute another model. A missing family is
an external handoff blocker, not an implementation failure, and no model is
treated as verified until the probe lists it.

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

### Immutable image and replay manifest

The manifest (`manifest_version` `pgrep-shadow-run/v4`) binds the run to the
exact code, image, corpus, and model state so a success is replayable:

- `worker.image` and `worker.image_digest`, the immutable `sha256:` digest the
  run actually executed;
- `code.sha` and `code.tree_status`, with `replayable` true only for a success
  produced from a clean tree;
- `corpus_index` fingerprint, `mtime_ns`, and size;
- `probe`, the full account catalog plus `sdk_version` and `model_catalog_hash`;
- `roles`, `allocation`, `seeds`, and `choice_permutations`;
- `prompt_versions`, `schema_versions`, and per-candidate `request_traces` with
  request hashes;
- `execution_mode` (`real` for a corpus run, `offline-self-check` for the
  smoke).

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
fake-client portfolio with no network, no Docker, and no key. It exercises
allocation, parsing, cross-verification, manifest assembly, and atomic
publication into the real quarantine root, then reports the run directory. This
is the per-commit-safe check; the account probe and any real run are on-demand.

### Troubleshooting

- `CURSOR_API_KEY is required for model probing or shadow mode`: export
  `CURSOR_API_KEY` or add it to `content/.env` (or a repo-root `.env`). The
  probe and real generation both need it; `shadow-smoke` and
  `shadow-worker-sync` do not.
- `Docker was not found`: install local Docker.
- `local runtime socket is unavailable` or `no verified local Unix socket`: the
  Docker CLI is present but the daemon is not running, or its socket is not one
  of the allowlisted local paths. Start the local engine. The runner will not
  fall back to a non-Docker path.
- `exact model <id> ... is not in the account probe` or `does not match its
  family identity`: run `just shadow-models`, use an exact listed ID per family,
  and never substitute. A missing family is an external blocker.
- A `_FAILED` run directory: read its `manifest.json` and `failures.json`. A
  preflight failure (missing Docker, missing model, mount-probe failure) records
  the redacted reason without touching the corpus.

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
| `just shadow-smoke`          | Offline fake-client shadow portfolio (`shadow_foundry.py --self-check`), no network, Docker, or key.               |
| `just shadow-models`         | On-demand account model probe; needs a running local Docker engine and `CURSOR_API_KEY`.                           |
| `just shadow-worker-build`   | Build the pinned Docker worker image and print its immutable digest; needs local Docker.                           |
| `just shadow-worker-sync`    | Install the worker's locked environment into `out/shadow-worker-venv`; no Docker or key needed.                    |
| `just shadow-foundry`        | Quarantined multi-model generation with exact `--sol-model`/`--opus-model`/`--grok-model`; never lands or pairs.   |
| `just check`                 | The overall gate (format, build, lint, all tests), which includes `test-py`.                                       |

The LLM audits and the foundry loop need the optional AI runtime and a key when
they call models; install it once with `just pgrep-ai-deps` and set
`OPENAI_API_KEY` (or add it to `content/.env`). `just foundry-dry`, `--dry-run`,
`just eval-verifier`, and the deterministic audits run without a key.

The shadow foundry is separate. `just shadow-smoke` and `just shadow-worker-sync`
run fully offline. `just shadow-models`, `just shadow-worker-build`, and
`just shadow-foundry` need a running local Docker engine, and the probe and real
generation also need `CURSOR_API_KEY` (in the environment, `content/.env`, or a
repo-root `.env`).
