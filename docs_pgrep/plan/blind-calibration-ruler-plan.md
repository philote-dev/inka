# Blind calibration ruler implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a frozen, stratified 120-item human ruler plus 12 hidden repeats
and generate blind, machine-parseable Pass A Markdown blocks for the user.

**Architecture:** Pure shipped modules own item hashing, stratification,
split/repeat assignment, and sheet parsing. Thin content tools load trusted,
known-failure, and finalized shadow inputs, publish a private calibration run,
and render at most 20 judgments per Markdown block. Hidden metadata remains only
in the private manifest.

**Tech Stack:** Python 3 standard library, existing content bundle and foundry
schemas, `review_sheet` conventions, `agreement` and `eval_verifier` contracts,
pytest, and `just`.

## Global constraints

- The primary ruler has exactly 120 unique items: 40 trusted existing, 40 known
  failures, and 40 finalized shadow candidates.
- Gold, external held-out, and ETS private items cannot appear in ruler inputs.
- The split is frozen before rendering: 80 calibration and 40 locked human
  validation items.
- Add exactly 12 hidden repeats. Repeats do not increase split support.
- All nine exact blueprint category slugs must appear.
- Pass A hides stored key, source, solution, decomposition, model identity,
  model output, verifier output, stratum, split, and repeat identity.
- Pass A contains only stem, five choices, a per-review relative figure link
  when present, and the approved machine-readable rubric. Raw SVG is stored as
  a separate asset and never appears in Markdown.
- Files contain at most 20 judgments and live below git-ignored
  `content/run/calibration/<run-id>/`.
- The manifest uses immutable SHA-256 content hashes and opaque review IDs.
- Unknown labels, incomplete fields, changed immutable content, duplicate IDs,
  or exposed hidden metadata fail import.
- Pass B is rendered only after a complete, valid Pass A import.
- CI uses synthetic fixtures and never reads the private content workspace.
- No acceptance unlock, threshold tuning, preference emission, or bundle landing
  occurs before human labels exist.
- No em dashes in code, comments, docs, commits, or chat.

---

## File structure

- Create `pylib/anki/pgrep/ai/calibration_ruler.py`: normalized item schema,
  content hash, source-stratum counts, deterministic sampling, split assignment,
  hidden repeats, and manifest validation.
- Create `pylib/anki/pgrep/ai/calibration_sheet.py`: Pass A and Pass B field
  schemas, reversible Markdown text protection, separate figure assets, strict
  parsing, immutable-content validation, and repeat consistency.
- Create `content/tools/build_calibration_ruler.py`: private input loading,
  firewall checks, run publication, index, and Pass A blocks.
- Create `content/tools/import_calibration_pass.py`: Pass A import, Pass B
  rendering, and Pass B import.
- Create `pylib/tests/test_pgrep_calibration_ruler.py`.
- Create `pylib/tests/test_pgrep_calibration_sheet.py`.
- Create `content/tools/test_build_calibration_ruler.py`.
- Create `content/tools/test_import_calibration_pass.py`.
- Modify `justfile`: add `calibration-ruler`, `calibration-import-a`, and
  `calibration-import-b`.
- Modify `docs_pgrep/reference/content-pipeline.md`: document the private human
  workflow.

---

### Task 1: Canonical ruler-item schema and immutable hash

**Files:**

- Create: `pylib/anki/pgrep/ai/calibration_ruler.py`
- Test: `pylib/tests/test_pgrep_calibration_ruler.py`

**Interfaces:**

- Produces `RulerItem`, `canonical_problem()`, `content_hash()`,
  `pass_a_hash()`, `pass_b_hash()`, `validate_source_item()`, and
  `BLUEPRINT_CATEGORIES`.
- Consumes problem dictionaries from the bundle, audit/rejection exports, and
  shadow candidates.

- [ ] **Step 1: Write failing schema/hash tests**

```python
# pylib/tests/test_pgrep_calibration_ruler.py
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import pytest

from anki.pgrep.ai import calibration_ruler


def _problem(**over):
    item = {
        "id": "p-1",
        "topic": "topic::mechanics::rotation",
        "blueprint_category": "mechanics",
        "stem": "A wheel rotates.",
        "choices": ["1", "2", "3", "4", "5"],
        "correct": "B",
        "source_ref": "OpenStax, p. 1",
        "solution_decomposition": [],
    }
    item.update(over)
    return item


def test_content_hash_ignores_hidden_metadata_but_not_content():
    first = _problem(model_family="sol", verifier={"decision": "accept"})
    second = _problem(model_family="grok", verifier={"decision": "reject"})
    assert calibration_ruler.content_hash(first) == calibration_ruler.content_hash(second)
    second["choices"][0] = "changed"
    assert calibration_ruler.content_hash(first) != calibration_ruler.content_hash(second)


def test_pass_a_hash_covers_only_visible_immutable_content():
    first = _problem(source_ref="Source A")
    second = _problem(source_ref="Source B")
    assert calibration_ruler.pass_a_hash(first) == calibration_ruler.pass_a_hash(second)
    second["stem"] = "Changed stem"
    assert calibration_ruler.pass_a_hash(first) != calibration_ruler.pass_a_hash(second)


def test_source_item_rejects_gold_and_heldout_markers():
    with pytest.raises(ValueError, match="private marker"):
        calibration_ruler.validate_source_item(
            _problem(source_ref="content/gold/problems/gold-1.json")
        )


def test_category_must_use_locked_slug():
    with pytest.raises(ValueError, match="blueprint_category"):
        calibration_ruler.validate_source_item(
            _problem(blueprint_category="Classical Mechanics")
        )
```

- [ ] **Step 2: Run RED**

```bash
PYTEST_ADDOPTS='-q pylib/tests/test_pgrep_calibration_ruler.py' just test-py
```

Expected: missing module.

- [ ] **Step 3: Implement canonicalization and hash**

```python
_CONTENT_FIELDS = (
    "stem",
    "choices",
    "figure",
    "source_ref",
    "solution_decomposition",
)


def canonical_problem(item: dict) -> dict:
    return {
        "stem": " ".join(str(item.get("stem", "")).split()),
        "choices": [" ".join(str(choice).split()) for choice in item.get("choices", [])],
        "figure": str(item.get("figure", "")),
        "source_ref": str(item.get("source_ref", "")),
        "solution_decomposition": item.get("solution_decomposition", []),
    }


def content_hash(item: dict) -> str:
    raw = json.dumps(
        canonical_problem(item),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def pass_a_hash(item: dict) -> str:
    visible = {
        "stem": " ".join(str(item.get("stem", "")).split()),
        "choices": [" ".join(str(choice).split()) for choice in item["choices"]],
        "figure": str(item.get("figure", "")),
    }
    raw = json.dumps(
        visible,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(raw.encode()).hexdigest()
```

Validate exactly five non-empty choices, A-E stored key (kept in the hidden
manifest), non-empty source reference, exact category, JSON-finite values, and
no private markers. `pass_b_hash()` analogously covers only the source excerpt
and decomposition displayed in Pass B. The private manifest stores all three
hashes.

- [ ] **Step 4: Run tests**

```bash
PYTEST_ADDOPTS='-q pylib/tests/test_pgrep_calibration_ruler.py' just test-py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pylib/anki/pgrep/ai/calibration_ruler.py pylib/tests/test_pgrep_calibration_ruler.py
git commit -m "feat(pgrep): add immutable calibration item schema"
```

---

### Task 2: Deterministic 40/40/40 sampling and 80/40 split

**Files:**

- Modify: `pylib/anki/pgrep/ai/calibration_ruler.py`
- Modify: `pylib/tests/test_pgrep_calibration_ruler.py`

**Interfaces:**

- Produces `RulerManifest`, `build_ruler()`, and `validate_manifest()`.
- `build_ruler(trusted, failures, shadow, *, seed=7)` returns 120 primary items
  plus 12 hidden repeats.

- [ ] **Step 1: Write failing composition tests**

```python
def test_ruler_has_locked_counts_splits_and_repeats():
    manifest = calibration_ruler.build_ruler(
        trusted=_fixture_items("trusted", 60),
        failures=_fixture_items("failure", 60),
        shadow=_fixture_items("shadow", 60),
        seed=7,
    )
    primary = [item for item in manifest.items if item.repeat_of is None]
    repeats = [item for item in manifest.items if item.repeat_of is not None]
    assert len(primary) == 120
    assert len(repeats) == 12
    assert Counter(item.stratum for item in primary) == {
        "trusted": 40,
        "failure": 40,
        "shadow": 40,
    }
    assert Counter(item.split for item in primary) == {
        "calibration": 80,
        "validation": 40,
    }
    assert {item.blueprint_category for item in primary} == set(
        calibration_ruler.BLUEPRINT_CATEGORIES
    )


def test_same_seed_is_byte_stable():
    first = calibration_ruler.build_ruler(*_inputs(), seed=7).to_dict()
    second = calibration_ruler.build_ruler(*_inputs(), seed=7).to_dict()
    assert first == second
```

- [ ] **Step 2: Add failure tests**

Cover insufficient stratum count, missing category, duplicate content hash,
gold/held-out marker, fewer than five human-positive and human-negative
candidate labels in either split when fixture labels are available, and split
overlap.

- [ ] **Step 3: Implement constrained deterministic selection**

Use a local `random.Random(seed)`. First reserve one item per category per
stratum where available, then fill remaining stratum quotas by deterministic
shuffle. Assign the validation split with category, stratum, conceptual versus
computational, and figure presence represented before filling remaining slots.

Review IDs are `cal-0001` through `cal-0120`. Repeat IDs are `rep-0001` through
`rep-0012`; `repeat_of` is stored only in the manifest. Shuffle all 132 display
items after repeat insertion.

- [ ] **Step 4: Run tests**

```bash
PYTEST_ADDOPTS='-q pylib/tests/test_pgrep_calibration_ruler.py' just test-py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pylib/anki/pgrep/ai/calibration_ruler.py pylib/tests/test_pgrep_calibration_ruler.py
git commit -m "feat(pgrep): build stratified blind calibration ruler"
```

---

### Task 3: Pass A Markdown blocks and blind index

**Files:**

- Create: `pylib/anki/pgrep/ai/calibration_sheet.py`
- Create: `pylib/tests/test_pgrep_calibration_sheet.py`

**Interfaces:**

- Produces `PASS_A_FIELDS`, `protect_markdown_text()`,
  `unprotect_markdown_text()`, `figure_assets()`, `render_pass_a_block()`,
  `render_blocks()`, and `render_index()`.
- Blocks contain at most 20 items.

- [ ] **Step 1: Write blind-rendering tests**

```python
def test_pass_a_contains_only_allowed_problem_content():
    rendered = calibration_sheet.render_pass_a_block(_manifest_item())
    assert "A wheel rotates" in rendered
    assert "**A)**" in rendered
    forbidden = [
        "correct",
        "source_ref",
        "model_family",
        "verifier",
        "calibration",
        "validation",
        "repeat_of",
        "solution_decomposition",
    ]
    assert not any(token in rendered for token in forbidden)


def test_blocks_are_capped_at_twenty():
    blocks = calibration_sheet.render_blocks(_manifest_items(132), pass_name="a")
    assert len(blocks) == 7
    assert all(block.count("\n### ") <= 20 for block in blocks)
```

- [ ] **Step 2: Implement the exact header instructions**

Copy the ten approved instructions from
`shadow-foundry-calibration-design.md`. Render the exact Pass A fields:

```text
your_answer:
stem_clear:
distractor_A:
distractor_B:
distractor_C:
distractor_D:
distractor_E:
figure:
difficulty:
overall:
notes:
```

Do not prefill a recommendation or default.

- [ ] **Step 3: Render figures safely**

Render only `![Figure](../figures/<review-id>.svg)` in Markdown. Return a pure
mapping from safe run-root-relative `figures/<review-id>.svg` paths to the exact
UTF-8 bytes of the SVG already validated by the immutable item schema. Distinct
review IDs, including repeats, receive distinct paths. Reject unsafe IDs,
traversal, absolute paths, ambiguous spaces, and collisions. The Markdown
contains no raw SVG.

- [ ] **Step 4: Run focused tests**

```bash
PYTEST_ADDOPTS='-q pylib/tests/test_pgrep_calibration_sheet.py' just test-py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pylib/anki/pgrep/ai/calibration_sheet.py pylib/tests/test_pgrep_calibration_sheet.py
git commit -m "feat(pgrep): render blind calibration Markdown"
```

---

### Task 4: Strict Pass A parser and immutable-content validation

**Files:**

- Modify: `pylib/anki/pgrep/ai/calibration_sheet.py`
- Modify: `pylib/tests/test_pgrep_calibration_sheet.py`

**Interfaces:**

- Produces `PassALabel`, `parse_pass_a()`, and `validate_pass_a_complete()`.

- [ ] **Step 1: Write failing round-trip and rejection tests**

```python
def test_pass_a_round_trip():
    sheet = _filled_pass_a_sheet()
    labels = calibration_sheet.parse_pass_a(sheet, manifest=_manifest())
    assert labels["cal-0001"].your_answer == "B"
    assert labels["cal-0001"].overall == "KEEP"


@pytest.mark.parametrize(
    "mutation, message",
    [
        ("missing_field", "incomplete"),
        ("unknown_label", "unknown value"),
        ("edited_stem", "immutable content"),
        ("duplicate_id", "duplicate review ID"),
        ("model_metadata", "hidden metadata"),
    ],
)
def test_pass_a_rejects_invalid_sheet(mutation, message):
    with pytest.raises(ValueError, match=message):
        calibration_sheet.parse_pass_a(
            _mutated_sheet(mutation),
            manifest=_manifest(),
        )
```

- [ ] **Step 2: Implement enumerated values**

Use exact frozen sets:

```python
ANSWERS = {"A", "B", "C", "D", "E", "UNSURE"}
PASS_FAIL = {"PASS", "FAIL", "UNSURE"}
DISTRACTOR = {"VALID", "INVALID", "CORRECT_ANSWER", "UNSURE"}
FIGURE = {"MATCHES", "CONTRADICTS", "UNNECESSARY", "MISSING", "N_A", "UNSURE"}
DIFFICULTY = {"1", "2", "3", "4", "5", "UNSURE"}
OVERALL = {"KEEP", "DROP", "UNSURE"}
```

The parser receives each linked figure's asset bytes separately. It decodes the
bytes as strict UTF-8 and recomputes `pass_a_hash` from the visible stem, choices,
and exact figure string, then compares the result with the private manifest. It
must restore stem and choice text with `unprotect_markdown_text()` rather than
stripping zero-width or other characters. It cannot recompute hidden source or
decomposition fields from Pass A, so it must not pretend the full
`content_hash` is visible. The Pass B parser performs the same check with
`pass_b_hash`. Neither parser trusts the visible review ID alone.

- [ ] **Step 3: Add hidden-repeat consistency**

`repeat_consistency(labels, manifest)` returns exact-answer agreement and
per-field raw agreement. It must exclude repeats from split support.

- [ ] **Step 4: Run tests**

```bash
PYTEST_ADDOPTS='-q pylib/tests/test_pgrep_calibration_sheet.py' just test-py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pylib/anki/pgrep/ai/calibration_sheet.py pylib/tests/test_pgrep_calibration_sheet.py
git commit -m "feat(pgrep): validate blind calibration labels"
```

---

### Task 5: Private ruler builder CLI and atomic Pass A publication

**Files:**

- Create: `content/tools/build_calibration_ruler.py`
- Create: `content/tools/test_build_calibration_ruler.py`
- Modify: `justfile`

**Interfaces:**

- Consumes explicit paths for trusted, failure, and finalized shadow JSON.
- Publishes `index.md`, `manifest.json`, `figures/<review-id>.svg`,
  `pass-a/block-*.md`, and `_SUCCESS`.
- Never writes Pass B before a valid Pass A import.

- [ ] **Step 1: Write failing CLI integration tests**

```python
def test_build_publishes_private_pass_a_workspace(tmp_path):
    run_dir = build_calibration_ruler.build(
        trusted_path=_write_items(tmp_path, "trusted", 50),
        failures_path=_write_items(tmp_path, "failure", 50),
        shadow_path=_write_items(tmp_path, "shadow", 50),
        out_root=tmp_path / "calibration",
        run_id="ruler-1",
        seed=7,
    )
    assert (run_dir / "_SUCCESS").exists()
    assert (run_dir / "manifest.json").exists()
    assert len(list((run_dir / "pass-a").glob("block-*.md"))) == 7
    assert (run_dir / "figures").is_dir()
    assert not (run_dir / "pass-b").exists()


def test_build_failure_leaves_no_final_directory(tmp_path):
    with pytest.raises(ValueError):
        build_calibration_ruler.build(
            trusted_path=_write_items(tmp_path, "trusted", 39),
            failures_path=_write_items(tmp_path, "failure", 50),
            shadow_path=_write_items(tmp_path, "shadow", 50),
            out_root=tmp_path / "calibration",
            run_id="bad",
            seed=7,
        )
    assert not (tmp_path / "calibration" / "bad").exists()
```

- [ ] **Step 2: Implement input loaders**

Accepted formats are lists or objects with `items`/`candidates`. Finalized
shadow input requires a sibling `_SUCCESS`, a complete three-model manifest,
and `synthetic: false`. Reject gold/held-out markers recursively.

- [ ] **Step 3: Implement atomic publication**

Reuse the exclusive lock, temporary sibling directory, `_SUCCESS`, and atomic
rename pattern from `content/tools/foundry.py`.

- [ ] **Step 4: Add recipe**

```just
# Build the private blind human ruler and Pass A Markdown blocks.
[unix]
calibration-ruler *args:
    {{ ninja }} pyenv
    out/pyenv/bin/python content/tools/build_calibration_ruler.py {{ args }}
```

- [ ] **Step 5: Run focused and full tests**

```bash
out/pyenv/bin/pytest -q content/tools/test_build_calibration_ruler.py
PYTEST_ADDOPTS='--ignore=qt/tests/test_installer.py' just test-py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add content/tools/build_calibration_ruler.py content/tools/test_build_calibration_ruler.py justfile
git commit -m "feat(pgrep): publish blind calibration ruler"
```

---

### Task 6: Pass importer and deferred Pass B renderer

**Files:**

- Create: `content/tools/import_calibration_pass.py`
- Create: `content/tools/test_import_calibration_pass.py`
- Modify: `justfile`

**Interfaces:**

- `--pass a`: validates every Pass A block, writes private
  `reports/pass-a-labels.json`, reports repeat consistency, and renders Pass B
  only when consistency floors pass.
- `--pass b`: validates Pass B and writes `reports/pass-b-labels.json`.

- [ ] **Step 1: Write failing Pass A import tests**

```python
def test_pass_a_import_renders_pass_b_after_consistency_pass(tmp_path):
    run_dir = _published_ruler(tmp_path)
    _fill_pass_a(run_dir, consistent=True)
    report = import_calibration_pass.import_pass(run_dir, "a")
    assert report["status"] == "PASS_A_COMPLETE"
    assert (run_dir / "reports" / "pass-a-labels.json").exists()
    assert len(list((run_dir / "pass-b").glob("block-*.md"))) == 7


def test_low_repeat_consistency_does_not_render_pass_b(tmp_path):
    run_dir = _published_ruler(tmp_path)
    _fill_pass_a(run_dir, consistent=False)
    report = import_calibration_pass.import_pass(run_dir, "a")
    assert report["status"] == "ADJUDICATION_REQUIRED"
    assert not (run_dir / "pass-b").exists()
```

- [ ] **Step 2: Implement Pass B fields and parser**

Use exact values:

```text
source_supports_stem: PASS | FAIL | UNSURE
source_supports_answer: PASS | FAIL | UNSURE
decomposition_correct: PASS | FAIL | UNSURE
decomposition_leaks_answer: PASS | FAIL | UNSURE
notes:
```

Pass B may reveal source excerpts and decompositions, but never model identity,
stored verifier verdicts, recommendations, split, or repeat identity.

- [ ] **Step 3: Add recipes**

```just
[unix]
calibration-import-a run:
    {{ ninja }} pyenv
    out/pyenv/bin/python content/tools/import_calibration_pass.py --run {{ run }} --pass a

[unix]
calibration-import-b run:
    {{ ninja }} pyenv
    out/pyenv/bin/python content/tools/import_calibration_pass.py --run {{ run }} --pass b
```

- [ ] **Step 4: Run tests and gate**

```bash
out/pyenv/bin/pytest -q content/tools/test_import_calibration_pass.py
just check
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add content/tools/import_calibration_pass.py content/tools/test_import_calibration_pass.py justfile
git commit -m "feat(pgrep): import two-pass human calibration labels"
```

---

### Task 7: Documentation and real Pass A handoff

**Files:**

- Modify: `docs_pgrep/reference/content-pipeline.md`
- Modify: `docs_pgrep/plan/shadow-foundry-calibration-design.md` only for
  verified implementation corrections.

- [ ] **Step 1: Document exact reviewer workflow**

Document:

```bash
just calibration-ruler \
  --trusted <trusted.json> \
  --failures <failures.json> \
  --shadow <shadow-run>/candidates.json \
  --run <run-id>

# User edits content/run/calibration/<run-id>/pass-a/block-*.md
just calibration-import-a <run-id>
```

- [ ] **Step 2: Run full offline verification**

```bash
just check
just shadow-smoke
```

Expected: PASS.

- [ ] **Step 3: Produce the real quarantined shadow pool**

Run the exact account-probed Sol, Opus, and Grok IDs. Require a finalized
three-family `_SUCCESS` run before continuing.

- [ ] **Step 4: Build the real ruler**

Use trusted and known-failure inputs that exclude gold and held-out material.
Run `calibration-ruler` with seed 7. Verify:

- 120 unique primary items;
- 12 hidden repeats;
- 80/40 split;
- 40/40/40 strata;
- all nine categories;
- seven Pass A block files;
- one byte-identical figure asset per displayed review ID that has a figure;
- no hidden metadata in any block.

- [ ] **Step 5: Stop for human labeling**

Return the exact `index.md`, `pass-a/`, and `figures/` paths. Do not import,
render Pass B, fit thresholds, unlock acceptance, or generate preference pairs
until the user finishes Pass A.

- [ ] **Step 6: Commit documentation only**

```bash
git add docs_pgrep/reference/content-pipeline.md docs_pgrep/plan/shadow-foundry-calibration-design.md
git commit -m "docs(pgrep): document blind calibration handoff"
```

---

## Plan self-review

- Spec coverage: immutable schema (Task 1), 40/40/40 ruler and 80/40 split
  (Task 2), Pass A blinding (Task 3), strict import and repeats (Task 4), private
  atomic workspace (Task 5), Pass B (Task 6), real Markdown handoff (Task 7).
- The first dependent plan must complete before Task 5 can consume a finalized
  shadow run.
- Human instructions are copied exactly into generated sheets.
- The plan stops at the requested milestone: generated Pass A Markdown ready for
  the user.
- Threshold fitting, standing-eval ingestion, acceptance unlock, and first-20
  accepted audit require human labels and belong to the post-label plan.
