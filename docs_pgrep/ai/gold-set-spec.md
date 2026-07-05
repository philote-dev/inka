# Gold Set Spec (E1), the ruler for AI generation

**Status: LOCKED (2026-07-03).** Owner: the Evaluation Architect track. This
defines the two gold sets that gate the AI layer (L4), the item schema for each,
and the scoring rubric. It does not contain the items themselves. Frank and the
content track author and verify the items. This spec says what qualifies, what
each item must carry, and how each is scored. The qualifying bar, the coverage
rule, and the raters are locked.

**Where this sits.** The gold set is the ground truth that graded AI output is
measured against (spec constraint 6). Card generation is graded against the card
gold set. Problem (MCQ) generation is graded against the problem gold set. The
cutoffs and the baselines the AI must beat live in `cutoffs-and-baselines.md`.
The held-out splits and the leakage rule live in `heldout-and-leakage.md`.

**Copy rule.** No em-dashes, sparing colons and semicolons, short labels.

---

## 1. Two gold sets, one job each

| Gold set                           | Grades                                               | Hardest part                    | Schema                                  |
| ---------------------------------- | ---------------------------------------------------- | ------------------------------- | --------------------------------------- |
| **Card gold set** (about 50 items) | card generation (stylize + gap-fill)                 | correct, useful facts           | `content/gold/gold-item.schema.json`    |
| **Problem gold set** (MCQ-shaped)  | problem generation (misconception-first distractors) | plausible, grounded distractors | `content/gold/gold-problem.schema.json` |

Both are hand-verified, both are evaluation-only, and both are covered by the
leakage rule. A gold item is never fed to the generator as a source or a
few-shot example. It is only ever a reference to grade against.

**Sources (LOCKED, v3).** The card gold set is about 50 cards verified against the
corpus (OpenStax, Fitzpatrick). It is not drawn from CWRU, because CWRU is a fed
card-generation example and nothing is both fed and graded. The PGRE is all
multiple-choice, so ETS contains no flashcards, there is no exam source for card
gold. The problem gold set is GR9677, a real ETS form vision-cleaned to gold-grade
text (about 40 to 50 verified items), plus the community 70 (57 keyed), both after
a quality pass and a dedup check. ETS is the problem gold source under v3: GR9677
is the authoritative ruler, and because gold is never fed, a real exam is the
strongest ruler available. It is never fed to generation. All of REA (both practice
exams, 200 MCQs) is fed as problem-generation examples, no split. Tier-3 items stay
private. See `heldout-and-leakage.md` section 2 for the full form
allocation.

**Boundary with the content track.** The content agent flags candidate items
(real questions, textbook facts, curated problems). This spec defines what turns
a candidate into a gold item: the required fields, the provenance anchor, the
verification trail, and the qualifying bar in section 4. Frank adjudicates.

---

## 2. The card gold item

Full schema in `content/gold/gold-item.schema.json`. A card gold item is a
verified question and answer with the evidence needed to grade a generated card
against it.

**Required.**

- `id`, `schema_version`, `type` (card).
- `card_kind`: `conceptual` or `computational`. This routes verification.
  Conceptual leans on provenance and human spot-check. Computational is
  CAS-checkable (SymPy).
- `topic` (two-level, matches the C2 taxonomy) and `blueprint_area` (one of the
  nine PGRE areas).
- `front` and `back`: the prompt and the correct answer.
- `fact_assertions`: the atomic checkable facts the item asserts, each flagged
  `must_hold`. This is the surface fact precision is scored on. A generated card
  that contradicts a `must_hold` assertion is a wrong-fact.
- `provenance`: tier plus a `source_ref` (title, section, and ideally a verbatim
  `quote_anchor`) so the fact traces to a real line.
- `verification`: who verified it, when, and by what method.
- `leakage_class`: fixed to `gold`.

**Conditional.**

- `solution_decomposition`: required for computational items, ordered sub-goals
  with a rubric each. Optional for conceptual.
- `computational`: a SymPy-parseable form, expected value, units, and tolerance,
  present when `card_kind` is computational.

**Note on distractors for cards.** The task brief listed a per-distractor
rationale on the card gold set. Cards in pgrep are retrieval items (front and
back), not multiple choice, so distractor rationales live on the problem gold
set where they have meaning. This is a marked decision for Frank in the
questions section. If Frank wants a small set of MCQ-shaped cards, they should go
in the problem gold set rather than blur the card schema.

---

## 3. The problem gold item (MCQ)

Full schema in `content/gold/gold-problem.schema.json`. The value and the risk of
problem generation both sit in the four distractors, so the schema makes each
distractor carry its misconception and rationale.

**Required.**

- `id`, `schema_version`, `type` (problem).
- `problem_kind`: `conceptual` or `computational`.
- `topic` and `blueprint_area`.
- `stem`: the question.
- `choices`: exactly five, labelled A to E, exactly one the key. Each distractor
  carries a `misconception_tag` (sign-error, wrong-law, unit-slip,
  limiting-case-confusion, and so on) and a `rationale` that says which error
  lands a student there. The key carries a rationale for why it is correct.
- `key`: the label of the correct choice.
- `solution_decomposition`: ordered sub-goals plus a rubric each, verified once.
  A problem without a verified decomposition does not qualify.
- `provenance`, `verification`, `leakage_class` as for cards.

**Conditional.**

- `computational`: a SymPy form for the key, optional forms tying each distractor
  to the misconception that produces it, units and tolerance.

**One key.** JSON Schema cannot count array booleans, so the loader enforces that
exactly one choice has `is_key` true and that it matches `key`. The schema notes
this in its `$comment`.

---

## 4. What qualifies an item

A candidate becomes a gold item only when all of these hold.

1. **Verified correct.** The key or the answer is checked against the named
   source, and for computational items also CAS-checked. Recorded in
   `verification.method`.
2. **Traceable.** A `source_ref` points at a real passage. Card gold anchors to
   the corpus (OpenStax, Fitzpatrick). Problem gold anchors to GR9677 (the cleaned
   real ETS form) and the community 70, with the physics checked against the corpus.
   ETS anchors the problem gold under v3, and because gold is never fed, that is
   allowed.
3. **Distractors annotated (problems).** Each wrong choice has a misconception tag
   and a rationale. GR9677 is a real ETS form with published solutions (the Faucett
   Omnibus covers it) that seed the rationales. The community 70 has none, so Frank
   authors those. Without the rationale the item cannot grade distractor quality.
4. **Decomposition present (problems, computational cards).** A verified
   sub-goal breakdown with a rubric per step.
5. **Blueprint-tagged.** Two-level topic plus one of the nine areas, so coverage
   can be checked against the blueprint weighting.

**Coverage target (LOCKED).** The card gold set is about 50 items. Spread both
gold sets across the nine PGRE blueprint areas by blueprint weight (Mechanics
and E and M heaviest, per `blueprint.md`), so the gate is not
dominated by one area. Per-area counts follow the blueprint weights.

---

## 5. Scoring rubric

Each generated batch is scored item by item against the gold set. Three measures,
matching `feature-forced-generation.md` and `feature-problem-generation.md`.

### 5.1 Fact precision

Per generated item, a binary judgement: are all asserted facts correct, with no
wrong-fact. Fact precision is the fraction of scored items with zero wrong-facts.
For computational items the SymPy path decides correctness. For conceptual items
the human rater decides, checking against the item's `fact_assertions` and the
named source. Fact precision is the first bar. A wrong-fact item fails
regardless of how well it teaches.

### 5.2 Useful-yield rate

Each generated item is sorted into one of three buckets, per
`feature-forced-generation.md`.

- **correct and useful**: right facts, and it actually teaches or tests the point.
- **wrong-fact**: a factual error. Fails fact precision.
- **correct but bad teaching**: right facts, but vague, trivial, giveaway, or
  off-target.

Useful-yield rate is `correct-and-useful / total scored`. This is the number the
gate leans on and the number the AI must beat the baseline on, because a keyword
or vector baseline can surface correct text but rarely produces a
correct-and-useful item.

### 5.3 Distractor quality (problems only)

Each distractor is scored on four criteria.

- **plausible**: a real student could pick it.
- **misconception-grounded**: it follows from a named error, not noise.
- **non-overlapping**: distinct from the other choices and not a paraphrase of
  the key.
- **source-grounded**: consistent with the corpus, not invented physics.

Two roll-ups. A per-distractor pass rate (fraction of distractors meeting all
four), and a per-problem pass rate (fraction of problems where all four
distractors pass). The per-problem rate is the stricter bar and the one the gate
uses, since a single weak distractor undermines the item.

### 5.4 Scoring process (keeps the numbers honest)

- **Two raters plus adjudication (LOCKED).** Rater 1 is Frank, rater 2 is an
  LLM-as-judge. Frank adjudicates disagreements. Report inter-rater agreement
  (for example Cohen's kappa) alongside the scores.
- **Blind to system.** Raters do not know whether an item came from the AI or
  from a baseline. Items from all systems are shuffled together before scoring.
- **Cutoffs first.** The passing bar and the baseline margin are frozen in
  `cutoffs-and-baselines.md` before any batch is scored. No moving the bar after
  seeing results.
- **Reproducible.** One command scores a batch and emits the three measures with
  bootstrap confidence intervals and the per-area breakdown.

---

## 6. Storage layout

```
content/gold/
  gold-item.schema.json        the card schema (this spec)
  gold-problem.schema.json     the MCQ schema (this spec)
  cards/gold-card-0001.json    one file per card gold item        (content track)
  problems/gold-problem-0001.json  one file per MCQ gold item     (content track)
```

Items live under `content/gold/` only, which is git-ignored and private. They
never move into the corpus, the index, or a prompt.

---

## 7. Decisions (resolved and locked)

Resolved and locked. Per-area counts follow the blueprint weights (section 4).
The second rater is an LLM-as-judge, with Frank adjudicating (section 5.4). The
qualifying bar (section 4) and the rubric (section 5) are locked. One sub-point
stays at Frank's discretion when authoring: whether to include any MCQ-shaped
cards. If he wants them, they go in the problem gold set, not the card schema
(section 2). See `ai-layer.md` for the full locked-decision set.

_Sources: `../reference/content-and-dependencies.md` (tiers, the four assets, the
leakage rule), `docs_pgrep/research/feature-forced-generation.md` (the gold-set
gate, fact precision, useful-yield), `docs_pgrep/research/feature-problem-generation.md`
(MCQ gold set, misconception-first distractors, distractor quality),
`docs_pgrep/plan/build-plan.md` (L4.0)._
