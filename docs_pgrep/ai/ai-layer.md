# The AI layer (L4): data, decisions, and evaluation

The durable reference for pgrep's AI layer: what it generates, the data it is
built on and graded against, the decisions that are locked, the leakage firewall
that keeps the evaluation honest, and where everything lives. This is the tracked
reference for the AI layer. The private data it operates on (the corpus, the gold
items, the held-out forms, the index) lives in the git-ignored `content/`
workspace.

**State (2026-07-04).** L4 is built and merged to `main`, off by default, so the
app demos and ships with AI on or off. The eval harness works, the gold sets are
built and validated, and the graded batch is generated. What remains is Frank's
short audit of the gold, then the scored re-run.

---

## 1. What L4 does

Three AI features, each grounded in the open corpus and graded against a gold set.

- **Card generation.** Gap-fill net-new cards from the corpus where the bundle
  lacks a technique, and stylize existing cards into the learner's voice. The
  graded path is gap-fill.
- **Problem generation.** MCQ with misconception-first distractors: name the
  likely error, derive the trap from it, store the misconception tag and rationale
  per distractor, plus a verified solution decomposition.
- **Scaffold-fade tutor.** The wrong-answer ladder over the stored decomposition,
  which never reveals the answer before the reveal rung.

Design rationale is tracked in `docs_pgrep/research/feature-forced-generation.md`,
`feature-problem-generation.md`, and `feature-productive-failure.md`.

---

## 2. The gold sets

The gold sets are the ruler graded AI output is measured against. They are
evaluation-only and never fed to generation.

### Problem gold, 118 items

- **61 from GR9677**, a real ETS form vision-cleaned to gold-grade text. Keys are
  the official ETS answers; distractor rationales and decompositions are drafts.
- **57 from the community 70**, clean stems with a source key, fully annotated (a
  misconception tag and rationale on every distractor, a decomposition, a
  two-level topic).
- Every community key got three independent opinions (source key, a gpt-4o solve,
  a gpt-5.5 solve): 39 unanimous, 13 where gpt-4o slipped but gpt-5.5 confirmed
  the key, 4 where gpt-5.5 dissented 2-to-1 (key stands), 1 genuine three-way
  split (`gold-problem-0115`) adjudicated to C, the correct answer.
- Spread across all nine areas, weighted toward Mechanics, E and M, and Quantum.

### Card gold, 50 items

- **Authored from the open corpus** (OpenStax, Fitzpatrick), each grounded in a
  retrieved passage with a verbatim quote anchor. Not from CWRU, because CWRU is a
  fed example and nothing is both fed and graded.
- Each carries atomic `fact_assertions` and a source ref; computational cards
  carry a SymPy form and a decomposition.
- Weight-proportional across areas, covering all 25 finest units.

### Verification

Every item is marked `pending-frank`. Keys are trusted (ETS official for GR9677,
three-way triangulated for the community), the drafts are machine-authored and
corpus-grounded, and Frank's sign-off (E4) is the last step. The item schemas are
`content/gold/gold-problem.schema.json` and `gold-item.schema.json`; what
qualifies an item is in `gold-set-spec.md`.

---

## 3. Gates and scoring (frozen)

The passing bars, the beat-baseline rule, and the raters are frozen in
`cutoffs-and-baselines.md` (the pre-registration for L4.0 round 1).
Do not move a bar after seeing results; a new round needs a new dated block.

**Card gate.** Fact precision >= 0.95, useful-yield >= 0.80, over a 50-card batch.
Useful-yield is the headline; fact precision is a hard floor.

**Problem gate.** Key correctness >= 0.95, all-four-distractors-pass per problem
>= 0.70, useful-yield >= 0.75, batch >= 30. Distractor quality is the headline;
key correctness is a hard floor.

**Beat-baseline.** The AI must beat the better of keyword and vector search by
>= 0.10 absolute on the headline metric, with the bootstrap CI of the advantage
excluding zero. Scored blind, side by side, against the same gold.

**Naive-distractor.** Reported comparison only, not a gate.

**Raters.** Rater 1 is Frank, rater 2 is an LLM-as-judge, Frank adjudicates.
Report inter-rater agreement. Score blind to system. Cutoffs frozen first.

**Coverage.** Spread both gold sets across the nine areas by blueprint weight.

---

## 4. ETS form allocation (v3)

Frank has academic permission for the ETS material, so copyright is not the gate;
evaluation integrity is. Under v3, no ETS form is fed to generation. One form
(GR9677) is the problem gold, a grading ruler that is never fed. Keeping every ETS
form out of generation is what makes the "beats a baseline on held-out ETS it
never saw" claim airtight.

| Form | Year | Role |
|---|---|---|
| GR0177 | 2001 | In-app exam mode + held-out Performance bank. Never fed. Clean text. |
| GR0877 | 2008 | In-app exam mode + held-out Performance bank. Never fed. Clean text. |
| GR9677 | 1996 | Problem gold source, vision-cleaned to gold-grade text (61 items). Never fed. |
| GR8677 | 1986 | Reserve held-out Performance bank. Never fed. Keys reliable, stems OCR-rough. |
| GR9277 | 1992 | Reserve held-out Performance bank. Never fed. Keys reliable, stems OCR-rough. |
| GR1777 | 2017 | Sealed final-readiness mock, plus the raw-to-scaled and percentile constants. |

**Fed examples (never graded).** Card generation is fed a clean non-ETS pool:
Brainscape (747 cards) and CWRU (292 cards). Problem generation is fed all of REA
(200 MCQs, both practice exams). These shape style and format only; they are never
the cited source and never become corpus.

---

## 5. The leakage firewall and generation safeguards

The firewall is structural first, then guarded.

- The index reads `content/corpus/` only. Nothing else is an index input.
- Everything under `content/tier3-private/`, `content/gold/`, and
  `content/heldout/` stays out of the index and every prompt. Retrieval returns
  corpus chunks only.
- From `content/tier3-private/`, only the numeric constants are ever read, never
  the items.
- The guard `content/tools/leakage_check.py` asserts no held-out or gold path
  appears in the index and that held-out shingles do not appear verbatim in it.

The safeguards that make the beats-a-baseline claim airtight:

1. **Name the split first.** The fed-versus-held split is written down before any run.
2. **Keep gold off the fed path.** Card gold is drawn from the corpus, not the fed
   CWRU set. The problem gold (GR9677 + community 70) is never fed.
3. **Reject memorized outputs.** Dedup generated items against every ETS form and
   every fed example (Brainscape, CWRU, REA), so a near-copy cannot pass as generated.
4. **Provenance.** Generated items ground their facts in the open corpus and cite
   it. ETS and the fed examples only shape style.
5. **Report fed versus held.** State exactly what was fed and what was held out.

Full detail: `heldout-and-leakage.md`.

---

## 6. The corpus and index

The corpus under `content/corpus/tier1-open/` is OpenStax University Physics Vol
1-3 and the three Fitzpatrick texts (Newtonian Dynamics, Quantum Mechanics,
Thermodynamics and Statistical Mechanics), licensed in `corpus/tier1-open/
LICENSES.md`. It is chunked and embedded with `BAAI/bge-small-en-v1.5` into
`content/index/corpus.db` (4,450 chunks), each chunk carrying a stable
`source_ref`. The keyword (FTS5 BM25) and vector baselines the AI must beat run
off the same index.

---

## 7. The eval run

- **Generated batch:** 50 card targets and 36 problem targets, three systems each
  (AI, keyword, vector, plus naive for problems), 294 candidates. 86 are AI items;
  18 of those were refused by the provenance layer (declined to cite a source),
  which is the safety behavior working.
- **Scoring:** held until the gold is frozen by Frank's audit. The current
  `content/run/score_report.json` and `run_manifest.json` are from an earlier
  smoke run and are stale; the real score lands after the audit.
- **Models:** generator `gpt-5.5-2026-04-23`, judge `gpt-5.4-mini-2026-03-17`,
  pinned in the run manifest. The gold was authored and cross-checked by gpt-4o
  and gpt-5.5, both different from the judge.

---

## 8. Frank's remaining review (the gate)

Frank is rater 1 and the adjudicator. The machine work resolved the hard parts,
so this is an audit, not a from-scratch grade.

1. Contested keys: done. The one ambiguous key (`gold-problem-0115`) is adjudicated.
2. Spot-check: skim a small sample (the 4 gpt-5.5-dissent problems `0095`,
   `0101`, `0102`, `0114`, plus a handful of random problems and cards).
3. Freeze: on the OK, the gold flips to verified and the scored batch runs on it.

Then touchpoint 2: rate the generated items blind against the frozen gold.

---

## 9. The pipeline scripts

Under `content/tools/`.

| Script | What it does |
|---|---|
| `build_index.py` | Chunk, embed, and index the corpus (leakage guard wired in) |
| `query_index.py` | Query the RAG index |
| `baselines.py` | The keyword and vector baselines |
| `run_batch.py` | Generate the graded batch (AI + baselines + naive) |
| `score_batch.py` | Blind-score a batch, gate metrics, bootstrap CIs, manifest |
| `eval_*.py` | Metrics, splits, judge, manifest for the scorer |
| `leakage_check.py` | Assert the firewall holds |
| `promote_gold.py` | Assemble problem gold from the clean candidates |
| `annotate_community.py` | Draft distractor rationales + a gpt-4o solve for community items |
| `crosscheck_keys.py` | Independent gpt-5.5 re-solve of every community key |
| `fill_confirmed.py` | Fill the one distractor left blank when gpt-4o slipped |
| `author_card_gold.py` | Author the 50 corpus-grounded card-gold items |
| `validate_gold.py` | Structural check over all gold files |

---

## 10. File map

The tracked AI-layer docs (this folder):

```
docs_pgrep/ai/
  ai-layer.md              this file
  gold-set-spec.md         what qualifies a gold item, the rubric
  cutoffs-and-baselines.md the frozen pre-registration (read by the harness)
  heldout-and-leakage.md   the held-out splits and the leakage firewall
  blueprint.md, slugs.md   the topic taxonomy
```

The private, git-ignored workspace (the data and the harness):

```
content/
  README.md               the workspace map
  manifests/              sourcing-plan.md, ingest-manifest.md, attribution.md, extraction-plan.md
  corpus/tier1-open/      the only thing the AI reads (indexed)
  index/corpus.db         built from corpus/ only
  blueprint/blueprint.json the machine taxonomy the harness reads
  gold/
    gold-problem.schema.json, gold-item.schema.json
    problems/ (118), cards/ (50), candidates/
  examples/               fed few-shot pool (CWRU, Brainscape, REA), never indexed
  heldout/                hidden tests, never indexed or prompted
  tier3-private/          ETS forms, items, constants, sealed mock
  run/                    the generated batch and the score outputs
  tools/                  the pipeline scripts and the eval harness
  reference/              copyrighted lookup PDFs, never indexed
```
