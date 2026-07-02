# Feature — Forced Generation + AI Conforming (POV2)

**Status: in progress** — literature laid out; architecture to be composed with Frank.
Shared context in `README.md`. The scheduler it feeds is in `feature-interleaving.md`.

**Epistemic note (Frank's caution):** cohort research — felipe.caicedo (GRE-math generation + verification), adarsh.rajesh (CFA card-gen), ram.sarma (distractors) — is a strong starting point but **not taken on faith**. Claims are tagged: _[primary]_ (peer-reviewed / established technique), _[cohort — verify]_ (cohort synthesis to confirm independently), _[our bet]_ (reasoned, no direct evidence). Physics ≠ GRE-math: more conceptual + multi-step content, so verification transfers only partly.

## The thesis (POV2)

Not "user-made" vs "AI-made." **Forced user generation first** (pay the cognitive cost at novel-concept formation) → **AI-conformed scaling** (amortize the learner's style across the deck) → **verification gate** (no bad card enters).

## Why force generation — the effect

- **Slamecka & Graf 1978 — generation effect:** self-generated material is remembered better than read, even when semantically identical; holds across item types/methods/ages. Meta **d ≈ 0.40** (Bertsch et al.). _[primary]_
- **Pan / Wendt et al. 2022 (APA), six experiments:** user-generated vs premade flashcards — memory **d = 0.45**, application **d = 0.29**. _[primary — confirm exact numbers against the paper]_

### Diagram — the two-phase flow

```mermaid
flowchart TD
    New["New concept / topic cluster"] --> Seed["Learner authors ≥1 card (FORCED generation)"]
    Seed --> Sig["Seed becomes STYLE SIGNAL<br/>(phrasing, abstraction, format, depth)"]
    Sig --> Gen["AI generates related cards, conformed to the signal"]
    Gen --> Verify["Verification gate (see below)"]
    Verify -->|"pass"| Deck["Into the deck (FSRS-scheduled)"]
    Verify -->|"fail"| Rev["Reject / human review"]
    Seed --> Deck
```

## The AI generation + verification pipeline

```mermaid
flowchart TD
    Src["Named source (curated corpus / textbook passage)"] --> RAG["RAG-grounded generation + verbatim quote anchor"]
    RAG --> GenRate["Generate + rate in ONE structured call<br/>(front, back, difficulty, confidence, rationale)"]
    GenRate --> Route{"Card type?"}
    Route -->|"computational"| CAS["CAS / symbolic check (SymPy)"]
    Route -->|"conceptual"| Prov["Provenance check + human spot-check"]
    CAS --> Conf{"confidence ≥ 0.6 AND checks pass?"}
    Prov --> Conf
    Conf -->|"yes"| Dedup["Dedup (normalized-front hash)"]
    Conf -->|"no"| Queue["Human review queue / reject"]
    Dedup --> Gate["Gold-set gate (batch quality, below)"]
```

### The verification stack (ordered by trustworthiness)

1. **RAG grounding + source binding + verbatim anchors + enforced abstention** → provenance; mechanically satisfies the spec's "named source / no untraceable claims" rule. _[primary technique]_
2. **CAS / symbolic check (SymPy, PAL)** — decisive for **computational** cards. _[primary technique]_ **Physics caveat _[verify]_:** units, dimensional analysis, and *multiple valid symbolic forms* make physics derivations harder to auto-check than GRE-math arithmetic — confirm feasibility per card type.
3. **Self-consistency / multi-sample agreement** — generate N, keep agreement. _[primary]_
4. **Retrieval-grounded verification** — claim vs source passage. _[primary]_
5. **Independent LLM "critic" — WEAK.** Corpus + known LLM-eval finding: self-critics rubber-stamp and can introduce errors. Supplementary only. _[cohort + known finding]_

### Diagram — computational vs conceptual split

```mermaid
flowchart LR
    Card["Generated card"] --> T{"Computational or conceptual?"}
    T -->|"computational (formula / numeric / derivation)"| C["CAS-verified → HIGH trust<br/>(expect to reject many drafts)"]
    T -->|"conceptual (which principle / qualitative)"| K["Provenance + human spot-check<br/>(automation weaker; humans carry it)"]
```

_felipe's headline conclusion [cohort — verify]:_ layered verification can pass a strict gold-set gate for **computational** cards but rejects a large fraction of drafts; **conceptual** cards lean on provenance + human adjudication. For PGRE this means a **split pipeline**, and the conceptual half is where the risk concentrates.

## The gold-set gate (spec challenge 7f)

```mermaid
flowchart TD
    GS["50-item gold set (known-correct Q&A)"] --> Pre["Set passing cutoff BEFORE looking at results"]
    Batch["50 generated cards"] --> Score["Score each:<br/>correct+useful / wrong-fact / correct-but-bad-teaching"]
    Pre --> Decide{"Meets cutoff?"}
    Score --> Decide
    Base["Baseline: keyword / vector search"] -.->|"AI must beat this, side-by-side"| Decide
    Decide -->|"yes"| Ship["Enable generation"]
    Decide -->|"no"| Block["Block; fix pipeline"]
```

Metrics: **fact precision**, **useful-yield rate**; inter-rater process on the scoring. _[spec + cohort]_

## Problems (MCQ) generation — distractors

- Naive "ask the model for wrong answers" → **weak distractors**. _[cohort]_
- Validated: **misconception-first** — articulate the specific error/rule, *then derive* the trap. Frontier (2025): train on **real student selection data** (pairwise ranker for which wrong answers students pick). _[cohort — verify frontier claim]_ Directly relevant to PGRE's 5-choice traps.

## Style conformance (the novel bit)

- Mechanism: **few-shot conditioning** on the learner's seed card (phrasing / abstraction / format).
- **No direct effect-size evidence — this is our bet.** _[our bet]_ We validate it ourselves (does conforming reduce reschedules / lift engagement?), we don't cite it.

## Generation → FSRS bridge

```mermaid
flowchart LR
    Rate["difficulty 0–1 (from generation)"] --> D0["D0 = 1 + 9·difficulty"]
    Type["card type"] --> S0["S0 (initial stability) by type"]
    D0 --> Prior["Seed FSRS memory-state prior (draft)"]
    S0 --> Prior
```

Lets generation feed the scheduler directly, no separate rating pass. _[cohort — adarsh; verify the mapping constants in simulation]_

## What I'd independently verify (not take on faith)

- felipe's "passes strict gate but rejects many drafts" — the actual **reject rate**, and whether it holds for **physics** (more conceptual + multi-step than GRE-math).
- Slamecka & Graf and Pan/Wendt **effect sizes** vs the primary papers (ours came via BrainLift summaries).
- **CAS feasibility for physics** derivations (units, symbolic equivalence, multiple valid forms).
- The **distractor "2025 frontier"** claim (ram.sarma).
- Whether **cheap 2026 models** hit acceptable fact-precision on PGRE content, and cost/latency at deck scale.

## Locked (core) decisions

1. **Authoring quota — one conceptual seed per finest topic unit** (subtopic where subtopics exist — the big three; category otherwise). The human authors **conceptual** cards only. Rough load ~20–30 seeds total. This *is* the generation-effect surface **and** the style signal.
2. **Human/AI allocation by mechanism** (the principle behind the split):
   - **Conceptual → human-authored** — gain is the **generation effect** (organizing the big idea); AI least trustworthy here.
   - **Computational → AI-generated, user-rehearsed** — gain is the **testing/retrieval effect** (reps), not authoring; AI most trustworthy here (CAS-checkable).
   - Rule: `human effort ∝ (generation benefit × AI untrustworthiness)`.
3. **Style conformance scoped to conceptual** — few-shot the AI on the conceptual seed so conceptual siblings read like the learner's; computational cards use a clean **standard format** (formulaic; style matters little). _[our bet — validate ourselves, don't cite]_
4. **Verification (core-minimum):** provenance/RAG grounding + the 50-item **gold-set gate** + route `confidence < 0.6` to human review. CAS / self-consistency / critic layers **deferred** (only if core works). _[rooting in core, per Frank]_
5. **Problems curated for core** (ETS / Conquering the PGRE); AI problem generation + misconception-first distractors are a **later** bank-scaling feature (train-on-selection-data frontier needs users/synthetic).
6. **gen→FSRS:** keep the AI difficulty rating (feeds our selector's 60–85% band + computational/conceptual routing); do **not** seed FSRS `D0` for core (marginal; FSRS cold-starts fine).

## Still open (deferred)
- Exact verification-layer composition + thresholds (when we build it).
- How the style signal is extracted (few-shot template vs. richer).
- Whether a rare "author one computational exemplar" option is offered for power users.

_Sources: Slamecka & Graf 1978; Pan/Wendt 2022; Frank's PGRE + Hint-Generation BrainLifts; cohort chats (felipe GRE-math generation/verification, adarsh CFA card-gen, ram distractors); spec challenge 7f. Tags: [primary] / [cohort — verify] / [our bet]._
