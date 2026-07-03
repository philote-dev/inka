# pgrep — Documentation

**Product:** pgrep (a.k.a. "PGRE Speedrun") — a Physics GRE (PGRE) prep app built by forking Anki.
**Owner:** Frank Gonzalez
**Status:** Planning. All four features + UI/UX + technical architecture designed; build layers L0–L6 design-ready. Open design gaps tracked below.
**Governing project spec:** [`spec/Speedrun_ A Desktop + Mobile Study App Built on Anki.pdf`](spec/Speedrun_%20A%20Desktop%20+%20Mobile%20Study%20App%20Built%20on%20Anki.pdf)
**Learning-science basis:** [`spec/Spiky POV Literature Contentions.pdf`](spec/Spiky%20POV%20Literature%20Contentions.pdf) + PGRE BrainLift (Nessie).
**Last updated:** 2026-07-02

> Docs are grouped by purpose: **spec** (the assignment), **research** (the durable "why", literature-backed), **plan** (execution roadmap + phase-tagged build contracts), **design** (UI), **assets**, and **prod** (prototype + submission artifacts). Every doc carries its own locked decisions + evidence. Shared context (mission, constraints, exam facts, thesis) lives here.

## Documentation map

### Spec (the assignment)
- [`spec/`](spec/) — the governing project spec + the learning-science source PDFs.

### Research (the "why" behind every part)
- [`research/vision-and-structure.md`](research/vision-and-structure.md) — persona, user stories, app structure/IA, MVP + milestones.
- [`research/features.md`](research/features.md) — the four features together: how they map to the three scores + the session.
- [`research/feature-interleaving.md`](research/feature-interleaving.md) — interleaving + Layer-B selector + session structure.
- [`research/feature-forced-generation.md`](research/feature-forced-generation.md) — author-a-seed then AI-conform generation + verification.
- [`research/feature-productive-failure.md`](research/feature-productive-failure.md) — wrong-answer ladder + consolidation.
- [`research/feature-calibration.md`](research/feature-calibration.md) — honest 3-score calibration dashboard (model calibration).
- [`research/scoring-and-readiness.md`](research/scoring-and-readiness.md) — how the three numbers are computed: ranges, coverage gate, abstain rules, held-out eval.
- [`research/performance-model.md`](research/performance-model.md) — the Performance "smart formula" (PFA calibrated logistic), every metric diagrammed.
- [`research/technical-architecture.md`](research/technical-architecture.md) — sync + mobile (FFI) + desktop shell + data model + cross-cutting guarantees.
- [`research/attempt-log-storage.md`](research/attempt-log-storage.md) — attempt/event log store decision (A now, C-ready).
- [`research/anki-rooting-and-rust.md`](research/anki-rooting-and-rust.md) — the graded Rust engine change: file-level plan.

### Plan (execution)
- [`plan/build-plan.md`](plan/build-plan.md) — execution roadmap: build layers L0–L6, gates, subagent orchestration, example prompt.
- [`plan/setup-content-and-dependencies.md`](plan/setup-content-and-dependencies.md) — the "outside the code" plan: your tasks, content sourcing, external tools.
- [`plan/demo-runbook.md`](plan/demo-runbook.md) — how to record every required proof, deadline by deadline.
- [`plan/frontend-execution-guide.md`](plan/frontend-execution-guide.md) — Claude Design to Svelte repo handoff steps.
- [`plan/dev-harness.md`](plan/dev-harness.md) — dev + test harness notes.
- [`plan/l1-coordination-schema.md`](plan/l1-coordination-schema.md), [`plan/l2-api-contract.md`](plan/l2-api-contract.md), [`plan/l2.5-onscreen-proof.md`](plan/l2.5-onscreen-proof.md) — phase-tagged build contracts.

### Design (UI)
All design material lives in its own folder at the repo root [`design/`](../design/), outside this docs tree and owned by the design workflow. It holds both the design notes and the Claude Design export (components, tokens, guidelines, ui_kits, screens):
- [`../design/ux-foundation.md`](../design/ux-foundation.md) — UI/UX foundation: identity, design language, nav shell, manifold, surfaces, tech-stack.
- [`../design/claude-design-prompts.md`](../design/claude-design-prompts.md) — Claude Design prompts + repo handoff.

### Assets & prod (in the standalone `design/` folder)
Concept renders, the prototype, and submission artifacts live under the repo-root [`design/`](../design/), alongside the rest of the design material:
- [`../design/assets/`](../design/assets/) — UX concept renders (`../design/assets/ux/`) + claude-design notes.
- [`../design/prod/pgrep-prototype.html`](../design/prod/pgrep-prototype.html) — clickable prototype of the L2 desktop surfaces. Rehearsal + L2 visual spec. **Not the submission.**
- [`../design/prod/proofs/`](../design/prod/proofs/) and [`../design/prod/video/`](../design/prod/video/) — Wednesday proof logs + the video production kit.

## Open design gaps
The four features, UI/UX, technical architecture, and the **three-score model** are designed; build layers are ready.

- **Resolved:** scoring/readiness derivation + held-out eval methodology → [`research/scoring-and-readiness.md`](research/scoring-and-readiness.md) (spec constraints 3 + 4). Performance model **decided** → [`research/performance-model.md`](research/performance-model.md) (the "smart formula": PFA calibrated logistic; batting-average baseline; IRT rejected at n=1).
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
- ~70 five-choice MCQ / 2 hours, computer-delivered, **no guessing penalty**. ~1.71 min/question.
- Blueprint (stable 20+ yrs): Mechanics 20%, E&M 18%, Quantum 13%, Thermo/Stat Mech 10%, Atomic 10%, Optics/Waves 8%, Special Rel 6%, Lab 6%, Specialized 9%.
- Subscores (0–100, not equated): Classical Mechanics, E&M, Quantum + Atomic.

## Core thesis
The PGRE is **problem-solving-heavy, fact-recall-light** — so flashcards are its *weakest* tool. pgrep's reason to exist is the **memory → performance → readiness bridge** that stock Anki lacks:
- **Memory** = P(recall now) → FSRS, verified on held-out reviews.
- **Performance** = P(correct on a *new* exam-style question) → held-out item bank.
- **Readiness** = projected score with explicit range + uncertainty + coverage.
