# Held-out Splits and the Leakage Rule (E2)

**Status: LOCKED (2026-07-03).** Owner: the Evaluation Architect track. This
defines the three held-out data slices that validate the models (spec
constraint 4) and the written leakage rule that keeps them honest. It defines
the splitting method, the form allocation, and the enforcement. It does not
contain the held-out items. The two split points that remain (the Memory revlog
cutoff and the Performance partition size) are pinned at run time under the same
frozen discipline.

**Copy rule.** No em-dashes, sparing colons and semicolons, short labels.

---

## 1. The principle

A model is only trusted on data it never learned from. Every split here is
**time-based**, never random, so no information leaks across a card's or an
item's trajectory. And held-out material never touches the AI path. It stays out
of the corpus, out of the RAG index, and out of every generation and tutor
prompt. Gold sets (E1) follow the same rule. This doc writes that rule down and
says how it is enforced.

Three slices, one per score, matching `statistics-and-evaluation.md`.

---

## 2. The three held-out slices

**ETS form allocation (LOCKED, v3).** No ETS form is fed to generation. One form,
GR9677, is the problem gold (vision-cleaned real ETS, never fed); the rest are
held out or sealed. That keeps the beats-a-baseline-on-held-out claim airtight:
the generator never saw a real ETS item, and gold is never fed. The fed examples
come from a clean non-ETS pool instead (Brainscape, CWRU, all of REA).

| Form | Year | Role |
|---|---|---|
| GR0177 | 2001 | In-app exam mode plus held-out Performance bank. Clean text layer. Never fed. |
| GR0877 | 2008 | In-app exam mode plus held-out Performance bank. Clean text layer. Never fed. |
| GR9677 | 1996 | Problem gold source, real ETS vision-cleaned to gold-grade text (about 40 to 50 verified items). Never fed. |
| GR8677 | 1986 | Reserve held-out Performance bank, supplementary. Keys reliable, stems OCR-rough. Never fed. |
| GR9277 | 1992 | Reserve held-out Performance bank, supplementary. Keys reliable, stems OCR-rough. Never fed. |
| GR1777 | 2017 | Sealed final readiness mock plus readiness constants. Untouched. |

The hard rule holds across the whole pool: nothing is both fed and graded. Gold is
never fed, so GR9677 as the problem gold is fine. REA is no longer split: all 200
MCQs feed generation. Card gold comes from the corpus, not the fed CWRU set.

This v3 allocation supersedes the earlier REA-split version (REA exam 1 fed, exam 2
problem gold, no real ETS in the gold) and the original six-form ETS split (GR8677
and GR9277 fed, the problem gold a GR0877 slice). Under v3 no ETS is fed, the fed
examples are a clean non-ETS pool (Brainscape, CWRU, all of REA), and the problem
gold is GR9677 (vision-cleaned real ETS) plus the community 70. Frank plays GR0177
and GR0877 in the app, so his attempts double as held-out Performance data.
The sourcing manifest (`content/manifests/sourcing-plan.md`) is reconciled to this
table. Full rationale in `ai-layer.md` section 4.

### 2.1 Memory: a revlog tail

- **What.** A time-based tail of the review log. FSRS predicts retrievability
  `R`, the revlog records the actual pass or fail.
- **Calibration data (LOCKED, verify first).** Pull a small slice of the public
  `open-spaced-repetition/anki-revlogs-10k` dataset and show Frank the columns
  and the distributions before committing. If it does not fit, fall back to
  Frank's own accruing revlog. The dataset is generic Anki reviews, which is
  appropriate because Memory calibration tests the memory model, not physics.
- **Split.** `TimeSeriesSplit` on `answered_at`. Reviews before the cutoff train
  or tune, reviews after the cutoff are held out. Never split a single card's
  reviews across the boundary at random, because that leaks the card's future
  into its past.
- **Cutoff.** A date, or the last N weeks or the last fraction of reviews. This
  is a decision for Frank (defaults proposed in `cutoffs-and-baselines.md`).
- **Metrics.** Brier (primary), log-loss, ECE, reliability diagram. Beat a
  fixed-interval or SM-2-style baseline.
- **Leakage risk.** Low. The revlog is user data, not AI input. The only rule is
  the time boundary, never a random shuffle.

### 2.2 Performance: exam-style questions never seen during tuning

- **What (LOCKED).** The primary held-out Performance bank is GR0177 (2001) and
  GR0877 (2008), the two clean text-layer forms, never fed. Frank plays them in
  the in-app exam mode, so his attempts double as Performance validation data and
  add realism. Two older forms (GR8677, GR9277) are reserve held-out: their keys
  are reliable but the stems are OCR-rough, so they widen the bank without
  anchoring it. GR9677 is no longer in this bank; under v3 it is the problem gold.
  The generator never sees any of them.
- **Split.** Time-based on when the item entered the bank, or a designated
  held-out partition fixed before tuning. Items added after the cutoff are
  held out. Pin the partition and its size so it is reproducible.
- **Metrics.** Accuracy, AUC, Brier, reliability. Beat the topic base-rate
  (batting average) and a memory-only predictor, to prove Performance adds
  signal.
- **Leakage risk.** High. These are physics MCQs, exactly the kind of content the
  corpus and the generator handle. They must be physically separated (section 4)
  and must never be indexed or prompted. A held-out performance item must not
  appear as, or be paraphrased into, a generated problem.

### 2.3 Readiness: a private Tier-3 mock

- **What (LOCKED).** GR1777 (2017), one full sealed ETS practice test (Tier 3),
  used only to sanity-check the readiness mapping. It plays two roles from the
  one artifact.
  1. **Constants.** Its official raw-to-scaled conversion table (and percentile
     table) are the constants that turn an expected raw score into a 200 to 990
     scaled number (`three-scores.md` section 3). Constants only, not items.
  2. **Validation mock.** The scored items validate predicted scaled versus
     actual, reported as scaled-point MAE. With one or two mocks this is a sanity
     check, not a full validation, and is reported as such.
- **Split.** No split needed. The whole mock is held out by construction. It is
  never used to train or tune anything.
- **Leakage risk.** Highest, and also a licensing line. ETS items are
  copyright. They are never bundled, never shipped, never indexed, and never fed
  to generation. Only the numeric conversion table is used, and even that stays
  in the private folder.

---

## 3. The leakage rule (written down)

This is the hard rule from `../reference/content-and-dependencies.md` section 1, stated so it is
testable.

> **Leakage rule.** No gold item and no held-out item may ever enter the corpus,
> the RAG index, or any generation or tutor prompt. The corpus is Tier 1 and
> Tier 2 only. Tier 3 never enters the corpus, the index, or a prompt. From
> Tier 3, only the numeric raw-to-scaled and percentile constants are used, and
> they live in the private folder, never shipped as items.

Restated as five checks.

1. **Corpus is Tier 1 plus Tier 2 only.** The index build reads from
   `content/corpus/` and nothing else.
2. **Held-out never indexed.** No text under `content/heldout/` or
   `content/tier3-private/` appears in `content/index/`.
3. **Gold never indexed.** No text under `content/gold/` appears in the index.
4. **Held-out and gold never prompted.** No generation or tutor prompt contains
   text drawn from `content/heldout/`, `content/tier3-private/`, or
   `content/gold/`. Retrieval only ever returns corpus chunks.
5. **Tier 3 is constants only.** From `content/tier3-private/`, only the numeric
   tables are read by the readiness mapping. The items are never read by the AI
   path.

---

## 4. How it is enforced

Enforcement is by construction first, then by an automated guard.

**By construction (folder separation).**

```
content/
  corpus/          Tier 1 + Tier 2 only        the ONLY thing the AI reads
    tier1-open/
    tier2-mine/
  index/           built from corpus/ only     safe to delete and rebuild
  gold/            E1 ground truth             evaluation only, never indexed
  heldout/         E2 hidden tests             never indexed, never prompted
  tier3-private/   ETS mock + constants        never indexed, constants only
```

The index builder takes `content/corpus/` as its only input path. Retrieval only
ever queries `content/index/`. So the corpus, index, and prompt path structurally
cannot see gold, held-out, or Tier-3 text.

**By guard (a leakage check, proposed).** A `content/tools/leakage_check.py`
that fails loudly if any of the five checks breaks. Recommended shape.

- Hash every chunk source path in `content/index/` and assert none resolve under
  `gold/`, `heldout/`, or `tier3-private/`.
- Take a sample of n-gram shingles from held-out and gold items and assert none
  appear verbatim in the built index (catches accidental copy-in).
- Scan any saved prompt logs for held-out or gold shingles and fail on a hit.
- Assert the Tier-3 reader used by the readiness mapping opens only the constants
  file, not the items.

This runs as part of the L4.0 harness gate, before generation is enabled, and
again before any results are reported. It is a process guard, not a model.

**Scan status.** The fed non-ETS pool has already been checked against the Tier-3
ETS items. The scan found 0 verbatim ETS reprints among the 670 non-ETS items,
so no fed example restates a real ETS question.

---

## 5. Time-based splitting, the direct answer

- Memory uses `TimeSeriesSplit` on review time. Never random.
- Performance uses a time cutoff on when an item entered the bank, or a pinned
  held-out partition fixed before tuning.
- Readiness holds out the whole mock, so there is nothing to split.
- Splits are pinned with fixed seeds and recorded, so every number reproduces
  from one command (`statistics-and-evaluation.md`).

---

## 6. Decisions (resolved and locked)

The form allocation is locked (section 2): no ETS is fed, GR0177 and GR0877 are
the clean forms played in the app and the primary held-out Performance bank,
GR8677 and GR9277 are reserve held-out, GR9677 is the problem gold (vision-cleaned
real ETS, never fed), and GR1777 is the single sealed mock and the source of the
conversion and percentile constants. The Memory calibration data follows the
verify-first rule (section 2.1). Two split points are pinned at run time, not
guessed here: the Memory revlog cutoff and the Performance partition size. Both
are fixed and recorded before any held-out number is read, under the same
pre-registration discipline as the gate.

_Sources: `../reference/content-and-dependencies.md` (section 1, the four assets and
the leakage rule), `docs_pgrep/research/statistics-and-evaluation.md` (held-out
pipelines, time-based splits), `docs_pgrep/research/three-scores.md` (Readiness
mapping and the Tier-3 table), `docs_pgrep/plan/build-plan.md` (L4.0, L5)._
