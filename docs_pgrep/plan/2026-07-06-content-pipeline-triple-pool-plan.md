# Content pipeline (triple pool) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Triple the pgrep problem pool with an honest diagram vs text-only split, verify every diagram is real and matches its problem, and bring decomposition tutor coverage to 100 percent, all through the existing grounded multi-pass verification.

**Architecture:** Work in the `feat/content-triple-pool` worktree with `content/` symlinked in. Each expensive stage fans out to subagents that write per-batch run directories; the orchestrator is the single writer that merges, dedups, and applies to `content_bundle.json`. Figure need is decided up front per problem and verified by an independent judge. Anything uncertain routes to a disposable review file for Frank.

**Tech Stack:** Python (`out/pyenv`), OpenAI `gpt-5.5-2026-04-23` generator with a distinct judge snapshot, local ONNX retrieval over `content/index/corpus.db`, SymPy CAS, the shipped `pgrep.ai` core.

Reference spec: `docs_pgrep/plan/2026-07-06-content-pipeline-triple-pool-design.md`.

---

## Conventions

- Interpreter: `/Users/philote/projects/inka/out/pyenv/bin/python`, always run with CWD at the worktree root `/Users/philote/projects/inka/.worktrees/content-triple-pool` (so `_ai_path` resolves the worktree's own `pylib/anki`).
- Never run generation with `--apply` inside a subagent. Subagents write run dirs only. The orchestrator applies.
- Batch run dirs live under `content/run/triple/<stage>/<batch>/`.
- Review files live under `content/run/review/` as `NN-<stage>-<topic>.md`.

---

## Task 0: Worktree and baseline (DONE)

**Files:** none (setup)

- [x] Worktree `feat/content-triple-pool` created, `content/` symlinked, corpus reachable.
- [x] Toolchain verified: audit runs, AI core resolves to the worktree, local retrieval works.
- [x] API smoke: one decomposition generated without `--apply`.

---

## Task 1: Stage A tooling in `content/tools/generate_content_set.py`

**Files:**

- Modify: `content/tools/generate_content_set.py`
- Test: `content/tools/test_generate_content_set.py` (new, stdlib unittest, no API)

Add four things, all opt-in so the existing gate-batch behavior is unchanged when the new flags are absent.

- [ ] **Step 1: Add the topic-aware figure policy.**

```python
# Diagram-required share per area (spec table). A figure is only ever required
# where a diagram is genuinely natural; abstract areas skew text-only.
FIGURE_SHARE = {
    "mechanics": 0.50, "electromagnetism": 0.45, "quantum": 0.15,
    "thermodynamics": 0.40, "atomic": 0.15, "optics_waves": 0.55,
    "special_relativity": 0.10, "lab": 0.40, "specialized": 0.15,
}

def assign_figure_required(targets: list[dict]) -> None:
    """Stamp figure_required on problem targets, per-area count = round(share*n).

    Deterministic: within an area's problems, the first k by id get the figure.
    """
    from collections import defaultdict
    by_area: dict[str, list[dict]] = defaultdict(list)
    for t in targets:
        if t["kind"] == "problem":
            by_area[t["category"]].append(t)
    for area, items in by_area.items():
        items.sort(key=lambda z: z["id"])
        k = round(FIGURE_SHARE.get(area, 0.0) * len(items))
        for i, t in enumerate(items):
            t["figure_required"] = i < k
```

- [ ] **Step 2: Add grow mode and id continuation.** A `--grow N` flag builds N extra problem targets (weight-proportional, round-robin over finest units via the existing `topup_targets`) with ids continuing past the current bundle max. Load the bundle, compute `max_seq` from existing `p4-prob-NNNN` ids, seed the sequence there.

```python
def _max_prob_seq(bundle_path: str) -> int:
    import json, re
    b = json.load(open(bundle_path, encoding="utf-8"))
    seqs = [int(m.group(1)) for p in b["problems"]
            if (m := re.match(r"p4-prob-(\d+)$", p.get("id", "")))]
    return max(seqs) if seqs else 0
```

- [ ] **Step 3: Inject the figure instruction into the target query.** In `generate_for_targets`, when building the per-target instruction, append the mode line so `generate_problem` authors the right kind. Keep numbers-in-text explicit.

```python
FIGURE_INSTR = (
    " This problem is presented with a labeled diagram. Author a setup whose "
    "geometry or circuit topology is clarified by a figure, describe the setup "
    "fully in words, and keep ALL numeric values and units in the text (the "
    "figure will carry only symbolic labels). Reference the figure naturally "
    "(for example 'in the figure shown')."
)
TEXTONLY_INSTR = (
    " This problem is text-only. Make it fully self-contained in prose and "
    "LaTeX. Do NOT reference any figure, diagram, or 'as shown' image."
)
# when t.get("figure_required"): query += FIGURE_INSTR else query += TEXTONLY_INSTR
```

Carry `figure_required` onto the output item in `enrich`.

- [ ] **Step 4: Dedup against the existing bundle.** Extend `dedup_and_firewall` (or its caller) to preload normalized stem hashes from the shipped bundle into `seen`, so a new problem that clones an existing stem is dropped as a duplicate.

- [ ] **Step 5: Write the tests (no API).**

```python
# content/tools/test_generate_content_set.py
import generate_content_set as g

def test_assign_figure_required_counts():
    targets = [{"kind": "problem", "category": "optics_waves", "id": f"p4-prob-{i:04d}"}
               for i in range(10)]
    g.assign_figure_required(targets)
    n = sum(t["figure_required"] for t in targets)
    assert n == round(0.55 * 10)  # 6

def test_textonly_area_low():
    targets = [{"kind": "problem", "category": "special_relativity", "id": f"p4-prob-{i:04d}"}
               for i in range(10)]
    g.assign_figure_required(targets)
    assert sum(t["figure_required"] for t in targets) == 1  # round(0.10*10)
```

- [ ] **Step 6: Run tests.** `cd <worktree> && /Users/philote/projects/inka/out/pyenv/bin/python -m pytest content/tools/test_generate_content_set.py -v` (or `unittest`). Expected: PASS.

- [ ] **Step 7: Plan-only sanity.** Run with `--grow 275 --plan-only` and confirm the per-area target counts and figure_required tallies match the spec table (about 94 diagram-required).

---

## Task 2: Stage A run (subagent fan-out)

**Files:** run dirs under `content/run/triple/pool/<area>/`

- [ ] **Step 1: Split by area.** Nine batches, one per blueprint area, sized per the spec table (mechanics ~55 down to relativity/lab ~16).
- [ ] **Step 2: Dispatch one subagent per area.** Each runs `generate_content_set.py --grow <n_area> --only-area <area> --out content/run/triple/pool/<area>` (add a small `--only-area` filter), no `--apply`. Prompt each subagent with the conventions above and to report counts, flag tallies, and refusals.
- [ ] **Step 3: Merge.** Orchestrator concatenates the nine `content_set.json` batches, re-runs dedup against the bundle and within-merge, and assigns final contiguous ids.
- [ ] **Step 4: Route flagged.** Build review file `content/run/review/01-problems.md` for every flagged/refused/key-unconfirmed item (KEEP / FIX / DROP slots). Clean, key-confirmed, cited items are provisionally accepted.
- [ ] **Step 5: Checkpoint.** Write `content/run/triple/pool/merged.json` (accepted) and `pending_review.json`.

---

## Task 3: Stage B tooling (figures)

**Files:**

- Create: `tools/pgrep_figure_verify.py` (fidelity judge, uses a judge snapshot)
- Create: `content/tools/check_figure_necessity.py` (necessity/reference checks, stdlib)
- Test: `content/tools/test_check_figure_necessity.py` (new)

- [ ] **Step 1: Necessity/reference checker (pure, no API).** Given a problem list, flag: (a) `figure_required=false` items whose stem references a figure, (b) `figure_required=true` items with no valid `<svg>` after wiring. Reuse the audit's `_SVG_RE` and figure-convention checks.

```python
import re
FIG_REF = re.compile(r"\b(as shown|shown (?:above|below)|the (?:figure|diagram)|in the figure)\b", re.I)
def dangling_refs(problems):
    bad = []
    for p in problems:
        stem = p.get("stem", "")
        has_svg = "<svg" in stem
        refs = bool(FIG_REF.search(re.sub(r"<svg[\s\S]*?</svg>", " ", stem)))
        if refs and not has_svg:
            bad.append({"id": p["id"], "issue": "references a figure but has none"})
        if p.get("figure_required") and not has_svg:
            bad.append({"id": p["id"], "issue": "figure_required but no svg"})
    return bad
```

- [ ] **Step 2: Fidelity judge (`tools/pgrep_figure_verify.py`).** Given `{id, stem, svg}` records, ask a judge model (a snapshot different from the figure generator) to answer STRICT JSON `{"matches": bool, "missing": [str], "notes": str}`: does the SVG show the components, geometry, and labels the stem describes, with nothing contradictory. Output a JSON verdict list.
- [ ] **Step 3: Tests for the checker (no API).** Fixtures: a text-only stem with "as shown" and no svg (flagged), a figure_required with svg (ok), a text-only clean (ok). Run and expect PASS.

---

## Task 4: Stage B run (figures for figure-required)

**Files:** `content/run/triple/figures/`

- [ ] **Step 1: Select** the `figure_required` accepted problems from Task 2.
- [ ] **Step 2: Draw** with `tools/pgrep_figure_gen.py --ids <...> --json content/run/triple/figures/figs.json --html content/run/triple/figures/preview.html` (generate + refine), model `gpt-5.5`.
- [ ] **Step 3: Verify conventions** by running the audit's figure checks on each SVG; drop convention failures.
- [ ] **Step 4: Verify fidelity** with `pgrep_figure_verify.py`; `matches=false` goes to review file `content/run/review/02-figures.md` (KEEP / REDRAW / DROP FIGURE / KEEP TEXT-ONLY) with the preview link. Do not wire these yet.
- [ ] **Step 5: Necessity cross-check** with `check_figure_necessity.py` over the full accepted set; any dangling reference goes to the figures review file.

Wiring happens in Stage D after Frank's verdicts, so the bundle only ever gets verified figures.

---

## Task 5: Stage C tooling (variant count)

**Files:** Modify `content/tools/generate_decompositions.py`

- [ ] **Step 1: Parameterize the variant count.** Add `--variants N` (default 3). Thread it into `DECOMP_SYSTEM` by formatting the "Give 2 numeric variants" line to N, and use it in the too-few checks.

```python
ap.add_argument("--variants", type=int, default=3)
# system = DECOMP_SYSTEM.replace("Give 2 numeric variants", f"Give {args.variants} numeric variants")
```

- [ ] **Step 2: Confirm** the prompt reflects N with a quick `--smoke 1 --variants 3 --out /tmp/vcheck` run and inspect that subproblems carry ~3 variants.

---

## Task 6: Stage C run (decompositions to 100 percent)

**Files:** `content/run/triple/decomp/<batch>/`

- [ ] **Step 1: Build the id list.** The 97 existing problems without `decomposition_tutor` plus every accepted new problem from Stage A/B.
- [ ] **Step 2: Split into batches** (for example by area or by chunks of ~30 ids) and dispatch one subagent per batch: `generate_decompositions.py --ids <...> --variants 3 --out content/run/triple/decomp/<batch>` (no `--apply`). Multi-pass verification stays on.
- [ ] **Step 3: Merge** all batch `decompositions.json` into one map. Route any problem with fewer than two clean subproblems, or repeated key-unconfirmed flags, to review file `content/run/review/03-decomp.md`.
- [ ] **Step 4: Checkpoint** `content/run/triple/decomp/merged.json`.

---

## Task 7: Adjudicate review files (Frank in the loop)

- [ ] **Step 1: Present** the three review files to Frank (problems, figures, decomps). Pause.
- [ ] **Step 2: Apply** verdicts with a small applier: KEEP as-is, FIX per note (regenerate the single item), DROP removes it, figure verdicts choose wire/redraw/text-only.
- [ ] **Step 3: Delete** each review file after its verdicts are applied.

---

## Task 8: Stage D land and verify

**Files:** Modify `pylib/anki/pgrep/content_bundle.json` (worktree copy)

- [ ] **Step 1: Apply problems.** Append accepted new problems to the bundle, update `counts`.
- [ ] **Step 2: Wire figures.** `tools/pgrep_wire_figures.py --figures content/run/triple/figures/approved.json`.
- [ ] **Step 3: Apply decompositions.** Run `generate_decompositions.py --apply` restricted to the merged set, or a small applier that merges `merged.json` into the bundle by id.
- [ ] **Step 4: Strict audit.** `out/pyenv/bin/python tools/pgrep_content_audit.py --strict`. Expected: all hard invariants clear (citations, copy, counts, figure conventions).
- [ ] **Step 5: Tests.** `just test-py` (or the targeted `pylib/tests/test_pgrep_*`), plus an AI-off import proof (`python -c "import anki.pgrep.decomposition"` with no key), and a tutor-harness list smoke.
- [ ] **Step 6: Coverage report.** Problems by area, diagram vs text-only, decomposition coverage (target 100 percent). Write to `content/run/triple/REPORT.md`.

---

## Task 9: Finish

- [ ] **Step 1:** Commit focused changes on `feat/content-triple-pool` (only when Frank asks).
- [ ] **Step 2:** Merge to main (PR or fast-forward), remove the worktree, delete the branch.

---

## Self-review notes

- Spec coverage: pool growth (Task 1-2), diagram split + verification (Task 1 policy, Task 3-4 + necessity/fidelity), decomposition 100 percent + variants (Task 5-6), review convention (Task 2/4/6 emit, Task 7 adjudicate), landing + tests (Task 8). Covered.
- Single-writer bundle rule honored: subagents never `--apply`; the orchestrator applies in Task 8.
- Runtime app path untouched: only driver and offline tools change; `PROBLEM_SYSTEM` and `generate_problem` are not modified.
