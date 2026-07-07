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

## Commands

| Command                          | What it does                                                                      |
| -------------------------------- | --------------------------------------------------------------------------------- |
| `assemble_bundle.py`             | The single gated landing command: land, convert math, wire figures, run invariants. |
| `just test-py`                   | Runs the Python tests, including the content-bundle invariant gate (per-commit).  |
| `just audit-bundle-ai`           | Runs the five on-demand AI audits (pre-release or nightly, needs the AI runtime). |
| `just check`                     | The overall gate (format, build, lint, all tests), which includes `test-py`.      |

The LLM audits need the optional AI runtime and a key; install it once with
`just pgrep-ai-deps` and set `OPENAI_API_KEY` (or add it to `content/.env`). The
deterministic audits and the invariant gate run without a key.
