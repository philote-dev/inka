# Paper Configuration Record (Phase 0)

Locked with Frank on 2026-07-05. This is the frozen configuration the rest of the
`academic-paper` pipeline builds against. Copy rule applies (no em-dashes, sparing
colons, short labels).

| Parameter               | Value                                                                                                                                                                                                                                                 |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Working title           | pgrep: A Physics GRE Preparation System with Separated, Calibrated Readiness Scores                                                                                                                                                                   |
| Framing                 | Technical report on pgrep (what it is, how it works, how well it works). Not an "Anki fork" thesis.                                                                                                                                                   |
| Objective               | Present pgrep's design and evaluation: the exam-value study selector, the three separated and calibrated scores (Memory, Performance, Readiness), the provenance-gated AI item generation, and the held-out evidence, including where it falls short. |
| Paper type              | Technical report (narrative, light on venue conventions)                                                                                                                                                                                              |
| Discipline              | Learning engineering and educational data mining (CS plus learning science)                                                                                                                                                                           |
| Domain evidence profile | cs_ml (admits arXiv preprints and proceedings alongside peer-reviewed work)                                                                                                                                                                           |
| Target venue            | General and internal, shaped like an L@S / EDM / LAK systems-and-evaluation report                                                                                                                                                                    |
| Citation style          | APA 7th (author-year)                                                                                                                                                                                                                                 |
| Target length           | ~7,500 words                                                                                                                                                                                                                                          |
| Output format           | LaTeX (.tex + .bib), so it can be refined with latex-paper-en afterward                                                                                                                                                                               |
| Body language           | English                                                                                                                                                                                                                                               |
| Abstract                | English only (single abstract plus keywords)                                                                                                                                                                                                          |
| Author                  | Frank Gonzalez (single author, corresponding)                                                                                                                                                                                                         |
| Funding / COI           | None / none                                                                                                                                                                                                                                           |
| Style                   | pgrep house copy rule                                                                                                                                                                                                                                 |
| Organization            | Balanced: product framing up front, technical depth in the middle, evaluation and honest limitations at the end                                                                                                                                       |
| Anki mention            | One short Foundation subsection crediting the reused engine (FSRS, collection, sync) and licensing, then pgrep-focused throughout                                                                                                                     |
| Mandatory back-matter   | Data availability, ethics, AI-use disclosure, limitations (CRediT/COI/funding kept brief)                                                                                                                                                             |
| Operational mode        | full (all phases)                                                                                                                                                                                                                                     |
| Working dir             | docs_pgrep/paper/                                                                                                                                                                                                                                     |

## Built-by-pgrep vs reused (authorship boundary, confirmed)

**pgrep's own contributions (the focus of the report):**

- The points-at-stake study selector (the in-engine reorder, gather-then-limit second pass).
- The two-level PGRE topic taxonomy and blueprint weighting.
- The Attempt-log data model ("A now, C-ready").
- The three-score model: Memory derivation, the Performance PFA calibrated logistic, the Readiness raw-to-scaled mapping with coverage gating.
- The honest evaluation methodology and harnesses (held-out splits, leakage firewall, Brier / log-loss / ECE / reliability, beat-baseline, the ablation).
- The AI layer: card generation, misconception-first problem generation, the scaffold-fade tutor, the gold-set gate.
- All desktop surfaces plus the desktop shell takeover, and the native SwiftUI mobile companion.

**Reused (mentioned only as needed, credited once):**

- The FSRS memory model and retrievability.
- The collection/SQLite store, notetypes, and the revlog.
- The sync engine and self-hostable sync server (reused unmodified).
- The web-host mechanism (mediasrv plus the embedded webview).

## Locked framing decision: the Anki comparison

The ablation is reported accurately and strongly: pgrep's selector beats stock Anki
at every realistic study budget (20 to 30 reviews/day) and beats massed (blocked)
practice in every configuration. The tight-budget case (10 reviews/day, where stock
Anki edges ahead) is reported as an explained, expected trade-off of the
desirable-difficulty band, not hidden. Source of record: `content/run/ablation.md`
and `content/run/ablation_results.json` (run 2026-07-05).

## Honesty posture (locked)

Report negatives plainly, matching pgrep's "abstain beats bluffing" ethos:

- Performance is validated on seeded synthetic data at n=1 (validates the pipeline, not a human effect).
- The AI gold-set gate is not fully green on the absolute cutoffs (card fact-precision one step short; problem batch yield refusal-limited), though the AI beats every baseline including naive-distractor generation with CIs excluding zero.
- The human-vs-LLM-judge agreement is near zero (kappa about -0.03 on "useful"), which is itself a reported finding motivating the two-rater rule.

## Citation verification level

Advisory (mark only, default). The reference list is compiled from the source
footers Frank already assembled across the docs. DOIs and a few exact effect sizes
are flagged `[verify]` for a pre-submission verification pass. No DOI is fabricated.
