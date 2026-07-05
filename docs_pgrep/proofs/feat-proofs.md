# pgrep - Feature Proofs

Physics GRE prep, forked from Anki. The Friday layer: AI added and checked,
phone syncs with desktop. Every AI feature still runs with AI switched off.

**Commit:** `4a98581f5` · verify live with `git rev-parse HEAD`

## AI checking and safety

The AI layer (card generation, problem generation, the scaffold-fade tutor)
with its safeguards: every output cites a named source or is refused, the tutor
ladder never leaks the final answer, problem distractors are misconception-first,
and every path still works with AI off.

Tests (`pylib/tests/test_pgrep_ai_core.py`, `test_pgrep_generation.py`,
`test_pgrep_problem_gen.py`, `test_pgrep_tutor.py`):

```
$ python -m pytest -v pylib/tests/test_pgrep_ai_core.py pylib/tests/test_pgrep_generation.py pylib/tests/test_pgrep_problem_gen.py pylib/tests/test_pgrep_tutor.py
collected 21 items

test_pgrep_ai_core.py::test_dedup_normalizes_case_and_spacing PASSED      [  4%]
test_pgrep_ai_core.py::test_giveaway_verifier_flags_leaks PASSED          [  9%]
test_pgrep_ai_core.py::test_provenance_cite_or_refuse PASSED              [ 14%]
test_pgrep_ai_core.py::test_generate_card_grounded_and_confident PASSED   [ 19%]
test_pgrep_ai_core.py::test_generate_card_low_confidence_routes_to_review PASSED [ 23%]
test_pgrep_ai_core.py::test_generate_card_ungrounded_refuses PASSED       [ 28%]
test_pgrep_ai_core.py::test_generate_problem_misconception_first PASSED   [ 33%]
test_pgrep_ai_core.py::test_generate_problem_giveaway_in_decomposition_refused PASSED [ 38%]
test_pgrep_ai_core.py::test_cas_check_when_sympy_available SKIPPED        [ 42%]
test_pgrep_generation.py::test_ai_off_by_default PASSED                   [ 47%]
test_pgrep_generation.py::test_author_seed_adds_card_ai_off PASSED        [ 52%]
test_pgrep_generation.py::test_generate_ai_off_authors_seed_only PASSED   [ 57%]
test_pgrep_generation.py::test_gap_fill_ai_on_adds_grounded_card PASSED   [ 61%]
test_pgrep_generation.py::test_gap_fill_routes_low_confidence_to_review PASSED [ 66%]
test_pgrep_problem_gen.py::test_problem_gen_ai_off PASSED                 [ 71%]
test_pgrep_problem_gen.py::test_problem_gen_ai_on_adds_problem PASSED     [ 76%]
test_pgrep_problem_gen.py::test_problem_gen_giveaway_in_decomposition_refused PASSED [ 80%]
test_pgrep_tutor.py::test_grade_subgoal_ai_off_reveals_for_self_compare PASSED [ 85%]
test_pgrep_tutor.py::test_grade_subgoal_ai_on_grades PASSED               [ 90%]
test_pgrep_tutor.py::test_grade_subgoal_giveaway_probe_is_blocked PASSED  [ 95%]
test_pgrep_tutor.py::test_session_synthesis_ai_off_recap PASSED           [100%]

======================== 20 passed, 1 skipped in 0.17s =========================
```

## Eval harness and beat-baseline

The ruler every AI output is graded on: fact precision, useful-yield, and
distractor quality with bootstrap confidence intervals, the keyword and vector
baselines to beat, and the beat-baseline rule. The transcript below is the
offline smoke that proves the whole pipeline runs (metrics, CIs, beat-baseline,
kappa, manifest). It is not the graded batch: the real gate runs on the human
gold sets, and the illustrative smoke fixture reports GATE FAIL only because its
batch size is deliberately tiny.

```
$ python content/tools/score_batch.py --smoke
======================================================================
pgrep gold-set gate, batch score
======================================================================

--- card ---
  ai       n=6    useful_yield=0.833 [0.500, 1.000]
  keyword  n=6    useful_yield=0.333 [0.000, 0.667]
  vector   n=6    useful_yield=0.167 [0.000, 0.500]
  beat-baseline: best=keyword passes=True
     vs keyword  advantage=0.500 [0.167, 0.833] beats=True
     vs vector   advantage=0.667 [0.333, 1.000] beats=True

--- problem ---
  ai       n=4    useful_yield=1.000 [1.000, 1.000]  distractor/prob=1.000 [1.000, 1.000]
  keyword  n=4    useful_yield=0.250 [0.000, 0.750]  distractor/prob=0.000 [0.000, 0.000]
  vector   n=4    useful_yield=0.000 [0.000, 0.000]  distractor/prob=0.000 [0.000, 0.000]
  naive    n=4    useful_yield=0.500 [0.000, 1.000]  distractor/prob=0.000 [0.000, 0.000]
  beat-baseline: best=keyword passes=True
     vs keyword  advantage=1.000 [1.000, 1.000] beats=True
     vs vector   advantage=1.000 [1.000, 1.000] beats=True
  ...
  reject-memorized: 10/10 kept, 0 dropped
```

## Leakage firewall

Held-out and gold items never reach the index or a prompt. The guard is the
automated backstop: the index resolves to `content/corpus/` only, no long
verbatim span from any held-out or gold item appears in an indexed chunk, and no
shipped AI module touches a private root. Leaked test data zeroes the score, so
this runs at index build and again before any result is reported.

```
$ python content/tools/leakage_check.py -v
pgrep leakage check
------------------------------------------------------------
[PASS] index-paths      6 distinct sources indexed, all under content/corpus/
[PASS] copy-in-index    604 items, longest overlap 11 words (heldout:GR0177-004), under the 25-word copy-in bar
[PASS] copy-in-prompts  no prompt logs on disk to scan
[PASS] ai-path-refs     20 shipped pgrep file(s), no forbidden private-root access
------------------------------------------------------------
OK: firewall intact
```

## Two-way sync

Review on the phone and it lands on the desktop, and the reverse, with nothing
lost or double-counted. Reviews and Attempt events union by id; for the same
card on both devices the newer modification time wins. This reuses Anki's own
sync engine unmodified (nothing under `rslib/src/sync/` changes) against a
self-hosted server. The conflict rule is documented in
`docs_pgrep/contracts/L3-sync-conflict-rule.md`.

Test (`pylib/tests/test_pgrep_sync_roundtrip.py`), covering different cards
offline on two devices, the same card on both, the Attempt-log union, and
offline-then-sync:

```
$ python -m pytest -v pylib/tests/test_pgrep_sync_roundtrip.py
collected 1 item

test_pgrep_sync_roundtrip.py::test_sync_round_trip PASSED                 [100%]

============================== 1 passed in 5.71s ===============================
```

The on-device variant, the iOS FFI sync path uploading a review that a desktop
engine then downloads, runs with `just ios-sync-proof`.
