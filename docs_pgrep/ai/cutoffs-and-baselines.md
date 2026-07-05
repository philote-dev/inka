# Cutoffs and Baselines (E3), the pre-registered gate

**Status: LOCKED (L4.0 round 1), frozen 2026-07-03 by Frank Gonzalez.** Owner:
the Evaluation Architect track. This is the pre-registration. It names the
metrics, the passing bar, and the baselines the AI must beat, all decided
before any results are seen (spec constraint 6). The values below are locked.
The frozen block in section 6 is dated. A new evaluation round needs a new dated
block, not an edit to this one.

**Copy rule.** No em-dashes, sparing colons and semicolons, short labels.

---

## 1. Why pre-register

The gate only means something if the bar was set before the results were seen.
So this doc is written and frozen first, then generation runs, then a batch is
scored. Moving the bar after seeing scores voids the gate. The gold-set gate
diagram in `feature-forced-generation.md` makes this the first step: set the
passing cutoff before looking.

---

## 2. Metrics that decide the gate

From `gold-set-spec.md` section 5. All are scored against the gold sets by two
blind raters with adjudication.

| Metric | Applies to | Definition |
|---|---|---|
| **Fact precision** | cards, problems | fraction of items with zero wrong-facts |
| **Useful-yield rate** | cards, problems | fraction that are correct and useful |
| **Distractor quality (per problem)** | problems | fraction of problems where all four distractors pass all four criteria |
| **Key correctness** | problems | fraction of problems whose key is correct |

Useful-yield is the headline number for cards. Distractor quality is the headline
number for problems. Fact precision and key correctness are hard floors: an item
that fails them cannot count as useful.

---

## 3. The passing bar (LOCKED)

These are the cutoffs the batch must clear. All are locked by Frank. They do not
move for L4.0 round 1.

### 3.1 Card generation

| Bar | Locked | Status |
|---|---|---|
| Fact precision | >= 0.95 | LOCKED |
| Useful-yield rate | >= 0.80 | LOCKED |
| Batch size scored | 50 generated cards | LOCKED |

Reasoning for the proposals, to argue with. Fact precision is a near-hard floor
because a wrong physics fact is worse than no card, so it sits high. Useful-yield
is lower because pedagogy is harder and more subjective. Both are for the whole
batch, reported with a bootstrap confidence interval and a per-area breakdown.

### 3.2 Problem generation

| Bar | Locked | Status |
|---|---|---|
| Key correctness | >= 0.95 | LOCKED |
| Distractor quality (per problem, all four pass) | >= 0.70 | LOCKED |
| Useful-yield rate | >= 0.75 | LOCKED |
| Batch size scored | >= 30 | LOCKED |

Reasoning. The key must almost always be right, so key correctness sits high.
Distractor quality is the hard, novel part and the whole point of
misconception-first, so it gets its own explicit bar. The per-problem "all four
pass" framing is deliberately strict, because one giveaway distractor spoils the
item.

---

## 4. Baselines the AI must beat, side by side

The spec requires the AI to beat a simple baseline, measured side by side (spec
constraint 6, `feature-forced-generation.md`, `feature-problem-generation.md`).
Two named baselines, both run on the same corpus and the same topics as the AI,
scored blind in the same batch.

### 4.1 Keyword search (baseline A)

- **What.** A keyword or BM25 retrieval over the Tier 1 plus Tier 2 corpus. For a
  target topic it returns the top passage or the top existing card or problem.
- **Why.** It is the honest "you did not need AI, search would do" test.
- **Tooling.** Term-frequency retrieval over the same chunked corpus the RAG
  index is built from.

### 4.2 Vector search (baseline B)

- **What.** Dense retrieval over the same corpus with local embeddings
  (`BAAI/bge-small-en-v1.5`) and `sqlite-vec` cosine, returning the top passage or
  the top existing item.
- **Why.** A stronger retrieval baseline than keywords. If generation cannot beat
  retrieval, generation is not earning its place.
- **Tooling.** The same embeddings and vector store the toolchain smoke test
  already exercises.

### 4.3 How "beat" is decided

- **Same reference, same raters.** Baseline outputs and AI outputs are graded
  against the same gold set, shuffled together, raters blind to source.
- **Same metric.** Useful-yield for cards, distractor quality and useful-yield
  for problems.
- **Margin, locked.** The AI must exceed the better of the two baselines by
  **>= 0.10 absolute** on the headline metric, with the AI's advantage's
  bootstrap confidence interval excluding zero. LOCKED.
- **Problem-specific baseline.** For problems, misconception-first is also
  compared against naive-distractor generation (ask the model for four wrong
  answers with no misconception step), per `feature-problem-generation.md`. This
  is a **reported comparison only, not a hard gate**. LOCKED.

---

## 5. Held-out metric bars (L5, for reference)

The gold-set gate above governs L4 generation. The held-out model bars govern L5
and are detailed in `heldout-and-leakage.md` and `../research/statistics-and-evaluation.md`.
Named here so the whole pre-registration lives in one place.

| Score | Metric | Baseline to beat | Bar |
|---|---|---|---|
| Memory | Brier, log-loss, ECE | fixed-interval / SM-2 | DECISION |
| Performance | accuracy, AUC, Brier | base-rate + memory-only | DECISION |
| Readiness | scaled-point MAE | raw% = scaled guess | sanity only, low n |

These are set with Frank at the L5 boundary, before the held-out numbers are
seen, the same pre-registration discipline as the gate.

---

## 6. Pre-registration block (FROZEN once dated)

Nothing above the line is final until this block is filled and dated. After that,
the cutoffs do not move for that evaluation round. A new round needs a new dated
block.

```
PRE-REGISTRATION
  round:            L4.0-round-1
  date frozen:      2026-07-03
  frozen by:        Frank Gonzalez

  card gate
    fact precision >=        0.95
    useful-yield >=          0.80
    batch size =             50

  problem gate
    key correctness >=       0.95
    distractor quality >=    0.70
    useful-yield >=          0.75
    batch size =             30

  beat-baseline
    headline margin >=       0.10 absolute
    CI rule:                 advantage CI excludes 0
    naive-distractor:        reported (not a gate)

  raters
    rater 1:                 Frank
    rater 2:                 LLM-as-judge
    adjudicator:             Frank
```

---

## 7. Decisions (resolved and locked)

All decisions above are resolved and frozen in section 6. For the record: the
card bars (fact precision >= 0.95, useful-yield >= 0.80, batch 50), the problem
bars (key correctness >= 0.95, distractor quality >= 0.70, useful-yield >= 0.75,
batch >= 30), the beat-baseline margin (>= 0.10 absolute with the advantage CI
excluding zero), naive-distractor as a reported comparison not a gate, and the
raters (Frank plus an LLM-as-judge, Frank adjudicates). See
`ai-layer.md` for the full locked-decision set. The L5 held-out metric
bars in section 5 are set later, at the L5 boundary, under the same discipline.

_Sources: `docs_pgrep/research/feature-forced-generation.md` (the gold-set gate,
set the cutoff before looking, fact precision and useful-yield),
`docs_pgrep/research/feature-problem-generation.md` (distractor quality, naive
baseline, retrieval baseline), `docs_pgrep/research/statistics-and-evaluation.md`
(held-out metrics and baselines), `../reference/content-and-dependencies.md` (the
tiers and the leakage rule), `docs_pgrep/plan/build-plan.md` (L4.0, L5)._
