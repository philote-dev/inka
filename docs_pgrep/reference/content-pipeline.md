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
version-controlled, so the pipeline is reviewable and reproducible. The private
data it reads and writes stays git-ignored: the corpus, the gold and held-out
sets, the RAG index, the run artifacts, the ETS raw-to-scaled constants,
`content/.env`, and the local databases. The copyrighted and held-out material
never enters git, while the code that operates on it does. The deep modules the
tools share live under `pylib/anki/pgrep/` and ship with the app.

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

| Audit | Kind | Severity | What it checks |
| ---------------------------- | ------------- | -------- | ------------------------------------------------------------------------- |
| `answer_key`                 | LLM           | HARD     | Independently re-solve each problem, blind to the stored key, and flag disagreements. |
| `figure_fidelity`            | LLM           | HARD     | For each `pg-figure` problem, judge whether the SVG faithfully depicts the figure-stripped stem. |
| `decomposition_leak`         | deterministic | HARD     | Run the giveaway verifier on each decomposition variant against the parent's answer. |
| `distractor_plausibility`    | LLM           | SOFT     | Flag wrong options that are obviously wrong and free to eliminate. |
| `citation`                   | deterministic | SOFT     | Check each `source_ref` resolves against the corpus index; skips when the index is absent. |

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

`content/tools/calibrate_verifier.py` produces the card. Its `--self-check` runs
an offline smoke. The full run (`--labels`) consumes a per-property
human-labeled set (the calibration pass) and writes the card and the tuned
thresholds under `content/run/calibration/`. It is run directly, like the other
content tools. A `just` recipe will land alongside the other pgrep-ai recipes.

---

## The content foundry loop (Phase 2)

Phase 2 turns the verifier panel into a best-of-N generation loop: sample many
candidates per blueprint slot, verify each, and keep only the survivors. Design
and phasing live in
[`content-foundry-and-verifier-design.md`](../plan/content-foundry-and-verifier-design.md)
and the task plan
[`content-foundry-loop-plan.md`](../plan/content-foundry-loop-plan.md).

### Temptation (soft panel check)

`pylib/anki/pgrep/ai/temptation.py` scores each distractor by how often weaker
or proficiency-simulated solvers select it. Zero temptation is a free elimination
(the same failure mode the `distractor_plausibility` audit flags). When
`weak_clients` are wired into `Verifier`, a `temptation` check joins the panel
as SOFT: it records free-elimination labels in the verdict but does not change
the accept / reject / escalate decision until temptation is calibrated.

### Difficulty estimate (caveat)

`pylib/anki/pgrep/ai/difficulty.py` estimates an easy / medium / hard band from
weak solvers, not from a frontier model's solve-rate. Per
[2512.18880](https://huggingface.co/papers/2512.18880), that distinction matters:
a hard item for a strong model can look easy when scored by solve-rate alone.
Validate estimates against held-out ETS item difficulty offline; the Pearson helper
is for content tools, not CI.

### Foundry partition and N cap

`pylib/anki/pgrep/ai/foundry_loop.py` owns the sample-verify-partition loop.
`run_slot` generates N candidates for one blueprint slot, runs each through the
panel, and partitions results into `accepted`, `rejected`, and `escalated`.
`max_n_for_accuracy` caps N from calibrated verifier accuracy (floor 2, ceiling
8) so a weak verifier cannot over-prune a large candidate pool.

`content/tools/foundry.py` is the CLI. Offline modes never touch the network:
`--self-check` for smoke, `--dry-run` for a full partition with fakes. Online
generation will use the same partition once wired. Comparative multi-candidate
selection (`--compare`) is deferred to Phase 2.1.

### Escalation sheet and firewall path

Low-confidence panel verdicts land in `escalated.json`. Run
`content/tools/make_foundry_escalation.py` to render a Markdown review sheet
(`ESCALATE` / `KEEP` / `DROP` per item) via the shared `review_sheet.py`
contract. Foundry run artifacts stay under git-ignored `content/run/foundry/`
(accepted, rejected, and escalated JSON per run). Generation still reads only
`content/corpus/`; the leakage firewall is unchanged.

Accepted survivors still land only through `assemble_bundle.py` and the
per-commit invariant gate.

---

## Commands

| Command                          | What it does                                                                      |
| -------------------------------- | --------------------------------------------------------------------------------- |
| `assemble_bundle.py`             | The single gated landing command: land, convert math, wire figures, run invariants. |
| `just test-py`                   | Runs the Python tests, including the content-bundle invariant gate (per-commit).  |
| `just audit-bundle-ai`           | Runs the five on-demand AI audits (pre-release or nightly, needs the AI runtime). |
| `just foundry-dry`               | Offline foundry smoke (`foundry.py --self-check`), no network.                    |
| `just foundry`                   | Best-of-N foundry loop; needs AI runtime + key when online generation is enabled. |
| `foundry.py`                     | Sample, verify, partition; `--dry-run` offline, writes under `content/run/foundry/`. |
| `make_foundry_escalation.py`     | Build a human review sheet from `escalated.json` under `content/run/foundry/`.    |
| `calibrate_verifier.py`          | Offline smoke (`--self-check`) of the calibration stats and card assembly.        |
| `just check`                     | The overall gate (format, build, lint, all tests), which includes `test-py`.      |

The LLM audits and the foundry loop need the optional AI runtime and a key when
they call models; install it once with `just pgrep-ai-deps` and set
`OPENAI_API_KEY` (or add it to `content/.env`). `just foundry-dry`, `--dry-run`,
and the deterministic audits run without a key.
