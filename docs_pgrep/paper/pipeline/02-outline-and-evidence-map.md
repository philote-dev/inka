# Outline and Evidence Map (Phase 2)

Technical report, balanced organization, target ~7,500 words (excluding abstract and
back-matter). Every major claim lists its source of record so the draft never asserts a
number the docs cannot back. Approval gate: Frank confirms this outline before Phase 3
(argument) and Phase 4 (draft).

## Section outline with word budget

| #  | Section                              |  Words | Purpose                                                                                                              |
| -- | ------------------------------------ | -----: | -------------------------------------------------------------------------------------------------------------------- |
| 0  | Abstract + keywords                  |   ~200 | One-paragraph statement of pgrep, its four contributions, and the honest evidence.                                   |
| 1  | Introduction                         |   ~850 | The problem, the memory-performance-readiness gap, pgrep in one paragraph, contributions, the honesty posture.       |
| 2  | Background and foundation            |   ~650 | The PGRE; the reused engine (one Anki/FSRS subsection); the learning-not-performance frame.                          |
| 3  | System overview                      |   ~750 | Three pillars, the study loop, the six surfaces, desktop plus mobile, the attempt-log data model.                    |
| 4  | The study selector (points-at-stake) |   ~850 | The in-engine reorder: worth times weakness, difficulty band, anti-blocking, the safe seam.                          |
| 5  | The three-score model                | ~1,250 | Memory, Performance, Readiness: derivation, ranges, coverage gate, abstain.                                          |
| 6  | The AI layer                         |   ~950 | Card generation, misconception-first problems, the scaffold-fade tutor, provenance, gold-set gate, leakage firewall. |
| 7  | Evaluation                           | ~1,350 | Methodology, then Memory calibration, Performance, the AI gate, and the ablation, with negatives.                    |
| 8  | Discussion                           |   ~500 | Honesty by construction, the difficulty-band trade-off, AI as an upgrade not a dependency.                           |
| 9  | Limitations                          |   ~300 | n=1, synthetic Performance, AI cutoffs, judge disagreement, simulation not a human trial.                            |
| 10 | Conclusion                           |   ~250 | What pgrep is and what the evidence supports.                                                                        |
| 11 | Back-matter                          |   ~200 | Data availability, ethics, AI-use disclosure.                                                                        |

## Contributions (stated in the introduction)

1. An in-engine study selector that reorders due items by exam value (blueprint weight
   times weakness) inside a production spaced-repetition engine, without mutating
   scheduling state.
2. Three separated, honestly calibrated scores (Memory, Performance, Readiness), each
   with a range and an abstain rule, that never collapse recall into transfer.
3. A provenance-gated AI item layer (cards, misconception-first problems, a
   scaffold-fade tutor) that cites a named source or refuses, gated by a pre-registered
   gold-set test and a leakage firewall.
4. A reproducible, held-out evaluation for every model, reported with its negatives.

## Claim-to-evidence map

### Section 1: Introduction

- PGRE is problem-solving-heavy and fact-recall-light, so flashcards are its weakest
  tool. Source: `README.md` (core thesis), `research/vision-and-structure.md`.
- The memory-performance-readiness bridge is the reason to exist. Source: `README.md`,
  `research/three-scores.md`.
- AI is an upgrade, never a dependency (works with AI off). Source: `build-plan.md`
  invariants, `research/features.md`.

### Section 2: Background and foundation

- Reused engine: FSRS memory model, collection/SQLite, revlog, sync, web-host. Source:
  `research/technical-architecture.md`, `research/anki-rooting-and-rust.md`.
- FSRS-6 (fsrs-rs 5.2.0), power forgetting curve, top non-neural srs-benchmark
  performer. Source: `research/feature-interleaving.md` (engine facts), `research/three-scores.md`.
- Exam facts: 100 five-choice MCQ, 170 minutes, a one-quarter-point penalty per wrong
  answer, scaled 200 to 990, over the nine-area blueprint. Source: `README.md`, `ai/blueprint.md`.
- Learning is not performance. Source: Soderstrom and Bjork (2015) via `research/three-scores.md`.

### Section 3: System overview

- Three pillars: Cards to Memory, Problems to Performance, timed mocks to Readiness.
  Source: `research/vision-and-structure.md`, `research/features.md`.
- The two-door study loop, commit-before-reveal, interleaving within a door. Source:
  `research/feature-interleaving.md`, `research/feature-productive-failure.md`.
- Six desktop surfaces plus a native mobile companion, one shared engine, two-way sync.
  Source: `build-plan.md` (L2, L2.5, L3), `research/technical-architecture.md`.
- Attempt log as immutable notes ("A now, C-ready"), K1 to K5. Source:
  `research/attempt-log-storage.md`, `reference/tag-and-attempt-log-schema.md`.

### Section 4: The study selector

- New `ReviewCardOrder::PointsAtStake`, a gather-then-limit second pass in Rust. Source:
  `research/anki-rooting-and-rust.md`, `proofs/mvp-proofs.md`.
- worth = blueprint% times weakness, weakness = 1 minus mean FSRS R; band 60 to 85
  percent; anti-blocking K=3. Source: `reference/tag-and-attempt-log-schema.md`,
  `research/feature-interleaving.md`.
- Safe seam: never mutates due, interval, or memory_state; no undo record; queues in
  memory. Source: `research/anki-rooting-and-rust.md`, `proofs/mvp-proofs.md`.
- Tests: 3 Rust plus 1 Python. Source: `proofs/mvp-proofs.md`.

### Section 5: The three-score model

- Memory = blueprint-weighted mean FSRS R; Poisson-binomial range; abstain below 5
  reviewed cards. Source: `research/three-scores.md`, `research/statistics-and-evaluation.md`.
- Performance = PFA calibrated logistic over four features (mastery, difficulty, recent
  successes, recent failures), beta calibration, partial-pooling intervals; abstain
  below about 8 attempts; base-rate baseline. Source: `research/performance-model.md`.
- Readiness = expected raw (Poisson-binomial over per-topic p_t and blueprint question
  counts) mapped through the official raw-to-scaled table (Tier-3 constants) to a 200 to
  990 band with an 80 percent interval; coverage gate 70 percent, else abstain and name
  the uncovered exam. Source: `research/three-scores.md`, `ai/heldout-and-leakage.md`.
- One convention: 80 percent central intervals; abstain beats bluffing. Source:
  `research/statistics-and-evaluation.md`.

### Section 6: The AI layer

- Card generation: author-a-seed, then stylize (facts locked, 1:1) or gap-fill
  (net-new, grounded). Source: `research/feature-forced-generation.md`, `ai/ai-layer.md`.
- Problem generation: misconception-first distractors plus a stored, verified
  decomposition. Source: `research/feature-problem-generation.md`.
- Scaffold-fade tutor: the wrong-answer ladder over the stored decomposition; giveaway
  verifier; AI-off reveal-and-self-compare. Source: `research/feature-productive-failure.md`.
- Provenance cite-or-refuse; gold-set gate (card fact precision >= 0.95, useful-yield >=
  0.80; problem key >= 0.95, distractor quality >= 0.70, useful-yield >= 0.75);
  beat-baseline >= 0.10 with CI excluding zero. Source: `ai/cutoffs-and-baselines.md`,
  `ai/gold-set-spec.md`.
- Leakage firewall: index reads corpus only; guard asserts no gold/held-out path or
  verbatim shingle in the index; 0 verbatim ETS reprints among 670 fed items. Source:
  `ai/heldout-and-leakage.md`, `ai/ai-layer.md`, `proofs/feat-proofs.md`.

### Section 7: Evaluation

- Methodology: time-based held-out splits, pre-registered cutoffs, named baselines, one
  command, bootstrap CIs. Source: `research/statistics-and-evaluation.md`,
  `ai/cutoffs-and-baselines.md`, `ai/heldout-and-leakage.md`.
- Memory calibration (held-out anki-revlogs-10k): Brier 0.234, log-loss 0.743, ECE
  0.159; beats base-rate on the primary Brier; pinned to fsrs-rs 5.2.0. Source:
  `build-plan.md` (L5 status).
- Performance (held-out seeded synthetic, n=1 honesty): Brier 0.175 vs 0.268, accuracy
  0.775 vs 0.563; pre-registered beat-baseline passes. Source: `build-plan.md` (L5),
  `research/performance-model.md`.
- Readiness: 200 to 990 with an 80 percent range, coverage-gated at 70 percent; sanity
  check against a sealed mock, reported as low-n. Source: `research/three-scores.md`,
  `ai/heldout-and-leakage.md`.
- AI gate (L4.0, two raters, 2026-07-05, 157 verified gold, generator gpt-5.5): cards,
  Frank useful-yield 0.84, fact precision 0.90; problems non-refused near-perfect (key
  1.00, useful 0.92, distractors 0.96) but a 31 percent refusal rate drags the batch;
  beats keyword and vector by +0.74 (cards) and +0.67 (problems), beats naive-distractor
  by +0.42, all CIs excluding zero; human-vs-judge kappa about -0.03 (useful); absolute
  cutoffs not fully green. Source: `ai/ai-layer.md` (section 7), `plan/dataset-pipeline.md`.
- Ablation (n=1 synthetic, BWER pre-stated, run 2026-07-05): full beats blocked in all 6
  configs (+0.008 to +0.075, CIs exclude zero); full beats plain Anki at 20 and 30
  reviews/day (primary +0.0151) and loses at 10/day (an explained difficulty-band
  trade-off); K=3 null by construction. Source: `content/run/ablation.md`,
  `content/run/ablation_results.json`.
- Two-way sync proof: revlog and Attempt union-by-id, newer-mtime, offline-then-sync;
  reuses Anki's server unmodified. Source: `proofs/feat-proofs.md`,
  `reference/sync-conflict-rule.md`.

### Section 8: Discussion

- Honesty by construction: coverage gate and abstain make a faked readiness impossible.
  Source: `research/three-scores.md`, `research/feature-calibration.md`.
- The difficulty-band trade-off explains the tight-budget ablation loss. Source:
  `content/run/ablation.md`.
- The two-rater finding: an LLM-only gate would have been unreliable (kappa near zero).
  Source: `ai/ai-layer.md` (section 7).

### Section 9: Limitations

- n=1, no cohort; Performance validated on synthetic; simulation not a human trial; AI
  absolute cutoffs pending; Readiness mock is low-n. Source: `research/performance-model.md`,
  `content/run/ablation.md`, `ai/ai-layer.md`.

### Section 11: Back-matter

- Data availability: corpus is Tier-1 open (OpenStax, Fitzpatrick); ETS forms are
  private and never shipped; the private `content/` workspace is not distributed. Source:
  `reference/content-and-dependencies.md`, `ai/heldout-and-leakage.md`.
- Ethics and AI disclosure: AI generation and this report's drafting both used LLMs;
  provenance and gold-set gating govern generated content; licensing is AGPL-3.0 with
  Anki credited. Source: `reference/content-and-dependencies.md`, `build-plan.md` (constraint 9).

## Figures and tables (planned, all from recorded data)

- Table 1: the three scores at a glance (construct, model, calibration, abstain rule).
- Table 2: evaluation results summary (Memory, Performance, Readiness, AI gate).
- Table 3: the ablation grid (full vs blocked, full vs plain, by budget and exam gap).
- Figure 1: system data flow (attempt log to selector, scores, dashboard). Optional,
  from the mermaid sources in `research/features.md`.
- Figure 2: reliability diagram concept for Memory/Performance. Optional.
