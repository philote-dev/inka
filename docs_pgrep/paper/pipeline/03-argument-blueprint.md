# Argument Blueprint (Phase 3)

Per-section claim chains for the draft. Each section states its thesis, the sub-claims
that support it, the evidence for each, and the transition to the next. Evidence tags
point at the source of record (see `02-outline-and-evidence-map.md` for full paths).

## Global thesis

pgrep turns a spaced-repetition engine into an exam-readiness system that separates
recall from transfer and reports each honestly. It contributes an in-engine
exam-value selector, three calibrated scores, a provenance-gated AI item layer, and a
reproducible held-out evaluation reported with its negatives.

## Section 1: Introduction

- Thesis: the PGRE rewards problem-solving, so a recall-only tool is the wrong
  instrument; readiness needs a bridge from memory to transfer.
- Sub-claim A: flashcards measure recall, not transfer (learning is not performance;
  Soderstrom and Bjork, 2015). Evidence: framing.
- Sub-claim B: three questions need three instruments (recall now, apply to a new item,
  projected score). Evidence: `three-scores.md`.
- Sub-claim C: honesty is a design property, not a disclaimer (ranges plus abstain).
  Evidence: `statistics-and-evaluation.md`.
- Contributions list (four). Transition: to build this, start from a strong memory
  engine and add on top.

## Section 2: Background and foundation

- Thesis: pgrep reuses a proven memory engine and adds the exam-readiness layer.
- Sub-claim A: FSRS is a strong deployed memory model (srs-benchmark). Evidence:
  `feature-interleaving.md` engine facts.
- Sub-claim B: the reused parts are the engine, store, sync, and web host, credited and
  otherwise in the background. Evidence: `technical-architecture.md`.
- Sub-claim C: the learning-science base is interleaving, generation, productive
  struggle, and calibration. Evidence: the four feature docs.
- Transition: here is the system those pieces compose into.

## Section 3: System overview

- Thesis: three co-equal pillars map to the three scores through one study loop and one
  attempt log.
- Sub-claims: the two-door loop with commit-before-reveal; six desktop surfaces plus a
  mobile companion on one engine with two-way sync; the attempt log as the spine.
- Evidence: `features.md`, `vision-and-structure.md`, `technical-architecture.md`,
  `attempt-log-storage.md`. Transition: the first pillar's engine change.

## Section 4: The study selector

- Thesis: ordering study by exam value is a real engine change, done safely.
- Sub-claims: SQL orders at gather time, so a naive post-sort is insufficient, hence a
  gather-then-limit second pass; worth is blueprint times weakness with a
  desirable-difficulty band and anti-blocking; the seam never mutates scheduling state.
- Evidence: `anki-rooting-and-rust.md`, `mvp-proofs.md`, `feature-interleaving.md`.
  Transition: the selector feeds the scores.

## Section 5: The three-score model

- Thesis: three separate, calibrated numbers, each with a range and an abstain rule.
- Sub-claim A (Memory): blueprint-weighted FSRS retrievability, Poisson-binomial range,
  abstain under five cards. Evidence: `three-scores.md`.
- Sub-claim B (Performance): PFA calibrated logistic over four features, beta
  calibration, base-rate baseline, abstain under about eight attempts; IRT rejected at
  n=1. Evidence: `performance-model.md`.
- Sub-claim C (Readiness): expected raw mapped to a 200 to 990 scaled band with an 80
  percent interval, coverage-gated at 70 percent. Evidence: `three-scores.md`.
- Transition: AI can enrich the item pool without touching this math.

## Section 6: The AI layer

- Thesis: AI is an upgrade that must cite a source or refuse, and it is gated before it
  ships.
- Sub-claims: author-a-seed then stylize or gap-fill; misconception-first distractors
  plus a stored verified decomposition; the scaffold-fade tutor that never leaks the
  answer; provenance, the gold-set gate, and the leakage firewall.
- Evidence: `feature-forced-generation.md`, `feature-problem-generation.md`,
  `feature-productive-failure.md`, `ai/*`. Transition: does it work, on held-out data.

## Section 7: Evaluation

- Thesis: every model is measured on held-out data against a pre-registered bar, and the
  negatives are reported.
- Sub-claims and evidence (numbers in `02-outline-and-evidence-map.md`): methodology;
  Memory calibration; Performance on synthetic (n=1 honesty); Readiness low-n; the AI
  gate (beats every baseline, cutoffs not fully green, judge kappa near zero); the
  ablation (beats blocked everywhere, beats stock Anki at realistic budgets, loses at
  the tightest budget); the sync proof.
- Transition: what this means and where it falls short.

## Section 8: Discussion

- Thesis: honesty by construction is the through-line; the trade-offs are explainable.
- Sub-claims: the coverage gate makes a faked readiness impossible; the band trade-off
  explains the tight-budget loss; the two-rater rule was vindicated by near-zero kappa;
  AI-off still scores.

## Section 9: Limitations

- n=1 and no cohort; synthetic Performance; simulation is not a human trial; AI absolute
  cutoffs pending; the Readiness mock is low-n.

## Section 10: Conclusion

- Restate what pgrep is and precisely what the evidence supports, no overclaim.
