# Content foundry dataset and standing eval, Phase 3 implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Emit a firewall-safe preference dataset from foundry runs, wire a standing verifier eval recipe with bootstrap CIs, and keep an offline smoke in `just test-py` so the loop cannot regress silently.

**Architecture:** Pure dataset schema and emitter in
`pylib/anki/pgrep/ai/preference.py`, written by default under ignored
`content/run/foundry/`. Leakage checks extend `leakage_check.py`.
`just eval-verifier` fits on calibration labels, evaluates a separate held-out
slice, and prints the two-axis gate card. Tier 2 and Tier 3 remain documented
triggers only, not implemented.

**Tech stack:** Python 3, Phase 1 `agreement` / `calibrate_verifier`, Phase 2 `foundry_loop`, existing `eval_metrics.py` bootstrap helpers, `leakage_check.py`, `just`.

## Global Constraints

- Depends on Phase 1 and Phase 2 landing.
- Preference data never enters git. Schema and emitter code are tracked; the
  default JSONL under `content/run/foundry/` is ignored. Operators must protect
  custom output paths.
- Dataset grounds only on corpus-derived candidates. No gold, held-out, or ETS item text in pairs.
- No network in CI. Real eval needs the AI runtime and is on-demand.
- No generator fine-tuning and no distilled verifier in this plan (Tier 2/3 stay staged).
- Do not change the shipped bundle schema or the per-commit invariant gate.

---

## Final hardened contracts

The implementation retains schema version 1, with these final-review
constraints:

- A pair requires a non-empty run ID, slot topic and blueprint category,
  distinct item IDs, five non-empty choices, an `A` through `E` key, source
  references, accept and reject panel decisions, rejected failing gates, and
  finite values throughout.
- Only validated accepted by rejected combinations within one slot become
  pairs. Escalations, invalid candidates, and one-sided slots do not.
- Every nested key and value passes the private-marker firewall. JSONL errors
  include line numbers and nested paths. Run publication is atomic and refuses
  an existing run directory.
- Standing-eval labels contain explicit `calibration.properties` and
  `heldout.properties` objects. Thresholds fit calibration predicted positives
  only and remain fixed on held-out labels.
- Standing gates use held-out agreement, balanced accuracy, accepted precision,
  and measured consistency. A per-slot foundry summary with at least two
  non-empty slots and escalation at most 0.15 is also required for green.
- Foundry confidence intervals bootstrap slot-level rates. Legacy aggregates
  have point rates only. A valid red report is printed and exits 1; invalid
  input exits 2; the passing offline self-check exits 0.

The detailed code sketches below record the original TDD sequence. The hardened
contracts above and
[`../reference/content-pipeline.md`](../reference/content-pipeline.md) are
normative where a sketch differs.

---

## Phasing reminder

- Phase 1: trustworthy verifier.
- Phase 2: temptation, difficulty, best-of-N foundry, escalation sheet.
- **Phase 3 (this plan):** WS8 preference dataset, WS9 standing eval + gate wiring; document Tier 2/3 triggers.

## File structure

- Create `pylib/anki/pgrep/ai/preference.py` — schema validation + chosen/rejected pair emission.
- Create `pylib/tests/test_pgrep_preference.py`
- Modify `content/tools/foundry.py` — call emitter after each slot / run.
- Modify `content/tools/leakage_check.py` (or add `content/tools/foundry_leakage.py` imported by it) — refuse gold/ETS ids and private-root paths in foundry JSONL.
- Modify `content/tools/calibrate_verifier.py` — finish `--labels` path enough for eval (load labels, tune thresholds, write card), or add `content/tools/eval_verifier.py` that composes calibration + yield.
- Modify `justfile` — `eval-verifier` recipe.
- Modify `docs_pgrep/reference/content-pipeline.md`, design doc Tier 2/3 section with concrete triggers.
- Optional: tiny offline smoke already covered by unit tests; ensure `just test-py` includes the new files (automatic if under `pylib/tests/`).

---

### Task 1: Preference dataset schema and emitter

**Files:**

- Create: `pylib/anki/pgrep/ai/preference.py`
- Test: `pylib/tests/test_pgrep_preference.py`

**Interfaces:**

- Consumes: `foundry_loop.SlotResult` (or equivalent lists of accepted/rejected dicts).
- Produces:
  - Schema version `preference_schema_version = 1`
  - Pair record:
    ```python
    {
      "schema": 1,
      "slot": {"topic": str, "blueprint_category": str, ...},
      "chosen": {
          "id": str, "stem": str, "choices": [...], "correct": str,
          "source_ref": str, "panel": {"decision": "accept", ...},
      },
      "rejected": {
          "id": str, "stem": str, "choices": [...], "correct": str,
          "source_ref": str, "panel": {"decision": "reject", ...},
          "failing_gates": [str],
      },
      "run_id": str,
    }
    ```
  - `def validate_pair(pair: dict) -> list[str]` (empty list means ok)
  - `def pairs_from_slot(slot: dict, result: SlotResult, *, run_id: str) -> list[dict]`
    - For each valid accepted item A and valid rejected item R, emit one pair
      within the same slot, capped if needed. Invalid, escalated, and one-sided
      slots do not emit pairs.
  - `def write_jsonl(path: str, pairs: list[dict]) -> int`, an atomic overwrite
    that rejects invalid and duplicate pairs.

- [ ] **Step 1: Write the failing test**

```python
# pylib/tests/test_pgrep_preference.py
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from anki.pgrep.ai import preference, foundry_loop


def _item(i, decision="accept"):
    return {
        "id": f"cand-{i}",
        "stem": f"stem {i}",
        "choices": ["a", "b", "c", "d", "e"],
        "correct": "A",
        "panel": {"decision": decision, "checks": []},
        "reason": "key: disagree" if decision == "reject" else "",
    }


def test_pairs_from_slot_emits_chosen_rejected():
    result = foundry_loop.SlotResult(
        accepted=[_item(1, "accept")],
        rejected=[_item(2, "reject")],
        escalated=[],
    )
    pairs = preference.pairs_from_slot(
        {"topic": "optics"}, result, run_id="run-1"
    )
    assert len(pairs) == 1
    assert pairs[0]["schema"] == 1
    assert pairs[0]["chosen"]["id"] == "cand-1"
    assert pairs[0]["rejected"]["id"] == "cand-2"
    assert preference.validate_pair(pairs[0]) == []


def test_validate_pair_rejects_missing_fields():
    errs = preference.validate_pair({"schema": 1})
    assert errs  # non-empty


def test_validate_pair_rejects_private_id_prefixes():
    pair = {
        "schema": 1,
        "slot": {"topic": "optics"},
        "chosen": {
            "id": "gold-001",
            "stem": "s",
            "choices": ["a"] * 5,
            "correct": "A",
            "panel": {},
        },
        "rejected": {
            "id": "cand-2",
            "stem": "s",
            "choices": ["a"] * 5,
            "correct": "B",
            "panel": {},
            "failing_gates": ["key"],
        },
        "run_id": "r",
    }
    errs = preference.validate_pair(pair)
    assert any("gold" in e.lower() or "private" in e.lower() for e in errs)
```

- [ ] **Step 2: Fail on missing module**

- [ ] **Step 3: Implement**

```python
# pylib/anki/pgrep/ai/preference.py
"""Preference dataset emitter for foundry runs (WS8).

Chosen = panel accept. Rejected = panel reject with failing gates recorded.
Escalations are not preference pairs (human still owns them). Schema stays
stable so Tier 3 SFT/DPO can consume it later without rewriting the loop.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Any

from .foundry_loop import SlotResult

preference_schema_version = 1

_PRIVATE_ID_MARKERS = ("gold-", "heldout-", "ets-", "tier3-", "gr9677-", "gr1777-")


def _failing_gates(item: dict) -> list[str]:
    panel = item.get("panel") or {}
    checks = panel.get("checks") or []
    out = [
        c.get("name", "")
        for c in checks
        if isinstance(c, dict) and not c.get("passed", True) and c.get("severity") == "hard"
    ]
    if not out and item.get("reason"):
        # Fallback: first token before ':' in reason strings
        out = [part.split(":")[0].strip() for part in str(item["reason"]).split(";") if part.strip()]
    return [g for g in out if g]


def validate_pair(pair: dict) -> list[str]:
    errs: list[str] = []
    if pair.get("schema") != preference_schema_version:
        errs.append(f"schema must be {preference_schema_version}")
    for side in ("chosen", "rejected"):
        node = pair.get(side)
        if not isinstance(node, dict):
            errs.append(f"{side} missing")
            continue
        for k in ("id", "stem", "choices", "correct", "panel"):
            if k not in node:
                errs.append(f"{side}.{k} missing")
        iid = str((node or {}).get("id", "")).lower()
        if any(m in iid for m in _PRIVATE_ID_MARKERS):
            errs.append(f"{side}.id looks private: {iid}")
    if "run_id" not in pair:
        errs.append("run_id missing")
    if "slot" not in pair:
        errs.append("slot missing")
    if isinstance(pair.get("rejected"), dict) and "failing_gates" not in pair["rejected"]:
        errs.append("rejected.failing_gates missing")
    return errs


def pairs_from_slot(
    slot: dict, result: SlotResult, *, run_id: str, max_pairs: int = 64
) -> list[dict]:
    pairs: list[dict] = []
    for chosen in result.accepted:
        for rejected in result.rejected:
            pair = {
                "schema": preference_schema_version,
                "slot": {"topic": slot.get("topic"), **{k: slot[k] for k in slot if k != "topic"}},
                "chosen": {
                    "id": chosen.get("id", ""),
                    "stem": chosen.get("stem", ""),
                    "choices": list(chosen.get("choices") or []),
                    "correct": chosen.get("correct") or chosen.get("key") or "",
                    "panel": chosen.get("panel") or {},
                },
                "rejected": {
                    "id": rejected.get("id", ""),
                    "stem": rejected.get("stem", ""),
                    "choices": list(rejected.get("choices") or []),
                    "correct": rejected.get("correct") or rejected.get("key") or "",
                    "panel": rejected.get("panel") or {},
                    "failing_gates": _failing_gates(rejected),
                },
                "run_id": run_id,
            }
            if not validate_pair(pair):
                pairs.append(pair)
            if len(pairs) >= max_pairs:
                return pairs
    return pairs


def write_jsonl(path: str, pairs: list[dict]) -> int:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    n = 0
    with open(path, "a", encoding="utf-8") as f:
        for pair in pairs:
            if validate_pair(pair):
                continue
            f.write(json.dumps(pair, ensure_ascii=False) + "\n")
            n += 1
    return n
```

- [ ] **Step 4: Tests pass**

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(pgrep): preference dataset schema and emitter for foundry runs

EOF
)"
```

---

### Task 2: Wire emitter into foundry CLI + leakage guard

**Files:**

- Modify: `content/tools/foundry.py`
- Modify: `content/tools/leakage_check.py` (add a check that scans `content/run/foundry/**/*.jsonl` when present)
- Test: extend `test_pgrep_preference.py` or add a pure helper test for the id/path scanner

**Interfaces:**

- After `run_slot`, call `preference.pairs_from_slot` and `write_jsonl(out/preferences.jsonl, pairs)`.
- Leakage helper: `def foundry_jsonl_is_clean(path: str) -> list[str]` returning
  path- and line-aware errors if any nested key or value fails schema,
  private-marker, private-root, or copy-in checks.

- [ ] **Step 1: Test**

```python
def test_foundry_jsonl_flags_gold_id(tmp_path):
    from anki.pgrep.ai import preference
    bad = {
        "schema": 1,
        "slot": {"topic": "x"},
        "chosen": {"id": "gold-9", "stem": "s", "choices": ["a"]*5, "correct": "A", "panel": {}},
        "rejected": {
            "id": "c2", "stem": "s", "choices": ["a"]*5, "correct": "B",
            "panel": {}, "failing_gates": ["key"],
        },
        "run_id": "r",
    }
    p = tmp_path / "preferences.jsonl"
    p.write_text(json.dumps(bad) + "\n")
    errs = preference.scan_jsonl(str(p))
    assert errs
```

Add `scan_jsonl` to `preference.py`.

- [ ] **Step 2–4: Implement scan + wire CLI + call from leakage_check when the directory exists**

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(pgrep): write preference JSONL and guard it in leakage_check

EOF
)"
```

---

### Task 3: Standing eval CLI and `just eval-verifier`

**Files:**

- Create: `content/tools/eval_verifier.py` (or extend `calibrate_verifier.py`)
- Modify: `justfile`
- Modify: `docs_pgrep/reference/content-pipeline.md`

**Interfaces:**

- `--self-check`: offline passing calibration, held-out, and per-slot foundry
  data; prints a green JSON report and exits 0.
- `--labels PATH`: load explicit calibration and held-out property arrays. No
  model client or network is involved.
- `--foundry-summary PATH`: load per-slot counts for cluster-aware yield and
  escalation intervals. It is required for green.
- `--out PATH`: write exactly the report printed to standard output.
- Use the unchanged `eval_metrics.bootstrap_ci` implementation with slot as the
  foundry cluster unit.

- [ ] **Step 1: Self-check test via subprocess or imported main**

```python
def test_eval_verifier_self_check_exits_zero():
    # Prefer importing a _self_check() function rather than subprocess in unit tests.
    from importlib.machinery import SourceFileLoader
    # Or: put pure self-check in preference/agreement already covered;
    # eval_verifier._self_check mirrors calibrate_verifier._self_check and also
    # asserts yield math on a tiny summary.
    assert True  # replace with real import of _self_check once file exists
```

Better concrete test: move yield summary math into `foundry_loop.summarize_runs(results: list[SlotResult]) -> dict` and unit-test that; CLI just prints it.

```python
def test_summarize_runs():
    from anki.pgrep.ai import foundry_loop
    r = foundry_loop.SlotResult(accepted=[{}], rejected=[{}, {}], escalated=[{}])
    s = foundry_loop.summarize_runs([r])
    assert s["accepted"] == 1
    assert s["rejected"] == 2
    assert s["escalated"] == 1
    assert abs(s["escalation_rate"] - 0.25) < 1e-9
```

- [ ] **Step 2–4: Implement summarize + eval_verifier CLI + just recipe**

```just
# Standing verifier eval. Offline: `just eval-verifier --self-check`.
# Full: `just eval-verifier --labels labels.json --foundry-summary summary.json`
eval-verifier *args:
    #!/usr/bin/env bash
    set -euo pipefail
    source "{{os_path}}"
    if [[ " {{args}} " == *" --self-check "* ]]; then
      {{python}} content/tools/eval_verifier.py {{args}}
    else
      conda run -n pgrep-ai --no-capture-output python content/tools/eval_verifier.py {{args}}
    fi
```

Adapt to the repo's actual justfile conventions (compare `audit-bundle-ai`).

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(pgrep): standing eval-verifier recipe and run summary

EOF
)"
```

---

### Task 4: Document Tier 2 / Tier 3 triggers and close the loop in docs

**Files:**

- Modify: `docs_pgrep/plan/content-foundry-and-verifier-design.md` (Staged tiers section)
- Modify: `docs_pgrep/reference/content-pipeline.md`
- Modify: `docs_pgrep/README.md` (link Phase 2 and Phase 3 plans)

**Concrete triggers to write into the design (no code):**

- **Tier 2 (distill verifier):** start when calibration card shows accept-precision >= 0.95 on key and figure, and at least 300 panel-labeled problems exist under `content/run/foundry/` (git-ignored count, operator-verified).
- **Tier 3 (SFT then optional DPO):** start when preference JSONL has >= 1000 validated pairs across >= 6 blueprint categories, leakage check clean, and Phase 3 standing eval is green on the latest calibration card.

- [ ] **Step 1: Edit docs**
- [ ] **Step 2: `just test-py` green**
- [ ] **Step 3: Commit**

```bash
git commit -m "$(cat <<'EOF'
docs(pgrep): preference dataset, standing eval, and Tier 2/3 triggers

EOF
)"
```

---

## Self-review checklist

1. **Spec coverage:** WS8 (Tasks 1–2), WS9 (Task 3), Tier 2/3 documentation (Task 4), firewall (Task 2).
2. **No placeholders:** schema fields and functions are named; Tier triggers are numeric.
3. **Consistency:** `preference_schema_version = 1`, `pairs_from_slot`, `scan_jsonl`, `summarize_runs` names match across tasks.
4. **Out of scope:** actual model distillation, SFT training jobs, IRT.

---

## Execution handoff

Plan complete and saved to `docs_pgrep/plan/content-foundry-dataset-and-eval-plan.md`.

Execute only after Phase 2 is merged. Same two options as Phase 2: subagent-driven or inline.
