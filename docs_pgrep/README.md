# pgrep — Documentation

**Product:** pgrep (a.k.a. "PGRE Speedrun") — a Physics GRE (PGRE) prep app built by forking Anki.
**Owner:** Frank Gonzalez
**Status:** Building. L0 through L4 are on `main`: desktop, mobile + two-way sync, and the AI layer (off by default). The current focus is L4's eval gate, where the gold sets are built and awaiting a short human audit. Then L5, L6. See [`plan/build-plan.md`](plan/build-plan.md).
**Governing project spec:** [`spec/Speedrun_ A Desktop + Mobile Study App Built on Anki.pdf`](spec/Speedrun_%20A%20Desktop%20+%20Mobile%20Study%20App%20Built%20on%20Anki.pdf)
**Learning-science basis:** [`spec/Spiky POV Literature Contentions.pdf`](spec/Spiky%20POV%20Literature%20Contentions.pdf) + PGRE BrainLift (Nessie).
**Last updated:** 2026-07-04

> Docs are grouped by purpose: **spec** (the assignment), **research** (the durable "why", literature-backed), **plan** (execution roadmap + phase-tagged build contracts), **design** (UI), **assets**, and **prod** (prototype + submission artifacts). Every doc carries its own locked decisions + evidence. Shared context (mission, constraints, exam facts, thesis) lives here.

## Documentation map

### Spec (the assignment)

- [`spec/`](spec/) — the governing project spec + the learning-science source PDFs.

### Research (the "why" behind every part)

- [`research/vision-and-structure.md`](research/vision-and-structure.md) — persona, user stories, app structure/IA, MVP + milestones.
- [`research/features.md`](research/features.md) — the four features together: how they map to the three scores + the session.
- [`research/feature-interleaving.md`](research/feature-interleaving.md) — interleaving + Layer-B selector + session structure.
- [`research/feature-forced-generation.md`](research/feature-forced-generation.md) — author-a-seed then AI-conform generation + verification (cards).
- [`research/feature-problem-generation.md`](research/feature-problem-generation.md) — AI problem (MCQ) generation: misconception-first distractors + its own gold set/eval.
- [`research/feature-productive-failure.md`](research/feature-productive-failure.md) — wrong-answer ladder + consolidation.
- [`research/feature-calibration.md`](research/feature-calibration.md) — honest 3-score calibration dashboard (model calibration).
- [`research/three-scores.md`](research/three-scores.md) — the three scores (Memory/Performance/Readiness): definitions, computation, coverage gate, abstain rules.
- [`research/statistics-and-evaluation.md`](research/statistics-and-evaluation.md) — the range math, the metrics, and the held-out evaluation pipelines behind the three scores.
- [`research/performance-model.md`](research/performance-model.md) — the Performance "smart formula" (PFA calibrated logistic), every metric diagrammed.
- [`research/technical-architecture.md`](research/technical-architecture.md) — sync + mobile (FFI) + desktop shell + data model + cross-cutting guarantees.
- [`research/attempt-log-storage.md`](research/attempt-log-storage.md) — attempt/event log store decision (A now, C-ready).
- [`research/anki-rooting-and-rust.md`](research/anki-rooting-and-rust.md) — the graded Rust engine change: file-level plan.

### Plan (execution)

- [`plan/build-plan.md`](plan/build-plan.md) — the unified build plan: current status, the remaining trajectory (L2.7, then L3 and L4, then L5, L6), the per-layer agent split, gates, and controller prompts.
- [`plan/dataset-pipeline.md`](plan/dataset-pipeline.md) — the status board for every dataset the AI layer needs (corpus, gold, held-out, examples): role, source, status, owner.
- [`plan/content-foundry-and-verifier-design.md`](plan/content-foundry-and-verifier-design.md) — verification-guided content foundry design (calibrated panel, best-of-N loop).
- [`plan/content-foundry-loop-plan.md`](plan/content-foundry-loop-plan.md) — Phase 2 implementation plan (temptation, difficulty, foundry loop).
- [`plan/content-foundry-dataset-and-eval-plan.md`](plan/content-foundry-dataset-and-eval-plan.md) — Phase 3 implementation plan (preference dataset, standing eval).

### Specs (durable, the code depends on)

- [`reference/tag-and-attempt-log-schema.md`](reference/tag-and-attempt-log-schema.md) — the two-level topic tags, the Attempt-log schema, and the K1-K5 invariants.
- [`reference/api-contract.md`](reference/api-contract.md) — the frontend-to-backend API contract, plus the desktop-takeover architecture (§6).
- [`reference/sync-conflict-rule.md`](reference/sync-conflict-rule.md) — the sync conflict rule (union-by-id on the Attempt log).

### Reference (operational how-to)

- [`reference/content-and-dependencies.md`](reference/content-and-dependencies.md) — content sourcing, provenance, the leakage firewall, the data assets, and the external toolchain.
- [`reference/content-pipeline.md`](reference/content-pipeline.md): the content pipeline's deep modules (one LLM seam, one Judge), the per-commit bundle invariant gate, and the on-demand AI audits.
- [`reference/dev-harness.md`](reference/dev-harness.md) — dev + test harness notes.

### AI layer (methodology + evaluation)

- [`ai/ai-layer.md`](ai/ai-layer.md) — the AI layer's data, locked decisions, leakage firewall, and evaluation. Start here for L4.
- [`ai/gold-set-spec.md`](ai/gold-set-spec.md) — what qualifies a gold item, and the scoring rubric.
- [`ai/cutoffs-and-baselines.md`](ai/cutoffs-and-baselines.md) — the frozen pass bars and the beat-baseline rule (the pre-registration).
- [`ai/heldout-and-leakage.md`](ai/heldout-and-leakage.md) — the held-out splits and the leakage firewall.
- [`ai/blueprint.md`](ai/blueprint.md), [`ai/slugs.md`](ai/slugs.md) — the PGRE topic taxonomy.

### Content workspace (`content/`: pipeline code tracked, data private)

The content pipeline code under `content/tools/` is version-controlled, so the pipeline is reviewable and reproducible. The private data the AI layer operates on stays git-ignored: the corpus, the gold and held-out ETS sets, the index, the run artifacts, the ETS constants, and `content/.env`. The copyrighted and held-out material is never committed; the code that operates on it is. The tracked pipeline architecture is in [`reference/content-pipeline.md`](reference/content-pipeline.md); the private workspace carries its own map:

- [`../content/README.md`](../content/README.md) — the workspace map: every folder and its data.

### Design (UI)

All design material lives in its own folder at the repo root [`design/`](../design/), outside this docs tree. It holds the UX spec and the reference renders; the living design system is the Svelte code in `ts/` (tokens in `ts/lib/sass/_pgrep.scss`, components in `ts/lib/components`, surfaces in `ts/routes/pgrep`):

- [`../design/ux-foundation.md`](../design/ux-foundation.md) — UI/UX foundation: identity, design language, nav shell, manifold, surfaces, tech-stack.
- [`../design/readme.md`](../design/readme.md) — the brand system (colors, type, voice), pointing at the live components.
- [`../design/assets/reference/`](../design/assets/reference/) — the concept renders and the logo mark.

### Proofs & prod

- [`proofs/`](proofs/) — the build proofs (clean build, tests, installer artifact, phone smoke logs).
- [`../prod/pgrep-prototype.html`](../prod/pgrep-prototype.html) — clickable prototype of the L2 desktop surfaces. A rehearsal aid, **not the submission**.
- [`../prod/video/`](../prod/video/) — the submission video kit (`submission-video-kit.md`) plus the concept walkthrough.

## Open design gaps

The four features, UI/UX, technical architecture, and the **three-score model** are designed; build layers are ready.

- **Resolved:** scoring/readiness derivation + held-out eval methodology → [`research/three-scores.md`](research/three-scores.md) (spec constraints 3 + 4). Performance model **decided** → [`research/performance-model.md`](research/performance-model.md) (the "smart formula": PFA calibrated logistic; batting-average baseline; IRT rejected at n=1).
- Smaller known open items: diagnostic placement algorithm (v0 scope); manifold interaction details ([`../design/ux-foundation.md`](../design/ux-foundation.md) §13); privacy/security specifics for keys + sync auth (sketched in [`research/technical-architecture.md`](research/technical-architecture.md) (e)).

## Mission

pgrep is a study environment for one graduate-level exam — the **Physics GRE (PGRE)** — built by forking Anki. It ships a **desktop app + phone companion sharing one engine**, and answers three different questions honestly: can the student **recall** a fact (memory), **apply** it to a new question (performance), and **what would they score** (readiness)?

## Governing constraints (from the project spec)

1. A **real change inside Anki's Rust engine** (not just Python/UI).
2. Two apps — **desktop + phone — sharing ONE engine**, with two-way sync.
3. Three **separate** scores: **memory / performance / readiness**, each with a range + a give-up rule.
4. **Held-out evaluation** for every model, reproducibly.
5. One **study feature** built on learning science, **ablation-tested** (full / feature-off / plain Anki).
6. Every **AI output** traces to a **named source**, is checked against a gold set, and beats a simple baseline.
7. Both apps **run with AI off** and still give a score.
8. Ship a desktop **installer** + a phone **build**.
9. License **AGPL-3.0-or-later**, crediting Anki.

## The exam: PGRE

pgrep models the real, modern PGRE as the shipped code does (`pylib/anki/pgrep/exam.py`, `readiness_constants.py`):

- **100 scored five-choice MCQ / 170 minutes**, computer-delivered, **formula-scored**: a one-quarter-point penalty per wrong answer (`raw = round(correct − incorrect/4)`, skips unpenalized). About 1.7 min/question.
- **Scaled 200–990** in 10-point steps, via the official raw-to-scaled conversion table (shipped as numeric constants only; see `readiness_constants.py`).
- Blueprint (stable 20+ yrs): Mechanics 20%, E&M 18%, Quantum 13%, Thermo/Stat Mech 10%, Atomic 10%, Optics/Waves 8%, Special Rel 6%, Lab 6%, Specialized 9%.
- The official report is a single total score, with no separately reported subscores. pgrep additionally breaks results down per blueprint category to drive coverage and the next-best-topic nudge.

## Core thesis

The PGRE is **problem-solving-heavy, fact-recall-light** — so flashcards are its _weakest_ tool. pgrep's reason to exist is the **memory → performance → readiness bridge** that stock Anki lacks:

- **Memory** = P(recall now) → FSRS, verified on held-out reviews.
- **Performance** = P(correct on a _new_ exam-style question) → held-out item bank.
- **Readiness** = projected score with explicit range + uncertainty + coverage.

## Submission status and known limitations

The spec rewards honest numbers over flattering ones, and honest negatives count as results. These are reported as such (detail in [`ai/ai-layer.md`](ai/ai-layer.md), [`ai/cutoffs-and-baselines.md`](ai/cutoffs-and-baselines.md), and the ablation run notes).

- **AI generation passes provenance and beats every baseline, but does not fully clear the pre-registered absolute cutoffs.** Under the human adjudicator of record, generated cards clear useful-yield (0.84 vs 0.80) but miss fact-precision by one step (~0.90 vs 0.95). Generated problems fall short on the absolute bars (key-correctness ~0.69 vs 0.95, distractor quality ~0.67 vs 0.70, useful-yield ~0.64 vs 0.75), dragged down by a ~~31% refusal rate even though the shipped non-refused problems score high (key 1.00). Every output still cites a named source or is refused, the AI beats keyword and vector retrieval (~~+0.74 cards, ~~+0.67 problems) and naive-distractor generation (~~+0.42) with CIs excluding zero, and the leakage firewall is green. The remaining gap is generation hardening, not gold-set or methodology.
- **The study-feature ablation is a simulation, not a human trial, and it reports a real negative.** On synthetic learners (n=1, pre-registered), the interleaving selector beats the blocked variant in all six configs (CIs exclude zero), and beats plain Anki at 20 and 30 reviews/day, but **loses to plain Anki at 10 reviews/day** (an explained difficulty-band trade-off at the scarcest budget). K=3 anti-blocking is memory-neutral by construction. The feature does not robustly beat stock Anki at every budget, reported plainly.
- **The iOS app is a review + scores + sync companion, being extended toward parity.** It runs real review sessions on the shared Rust engine via the C FFI, shows the three scores, and syncs two-way with desktop (`just ios-sync-proof`). It is a companion by design, not yet a full mirror of the desktop surfaces.
