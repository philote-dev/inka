# PGREP Features

**Status: all four designed (core).** Per-feature detail in the `feature-*.md` docs; shared context in `README.md`; build sequencing in `build-plan.md`.

## One-paragraph synthesis

pgrep stands on the shared **FSRS engine + our Layer-B selector**. Four learning-science features compose on top, each owning a different question:

- **Interleaving (POV1)** — the *order* you practice (which item next, across topics).
- **Forced generation (POV2)** — *what* you practice (how cards/problems get made).
- **Productive failure (POV3)** — *how* you work a problem (struggle → scaffolded help → consolidation).
- **Calibration (POV4)** — *whether you're ready* (honest scores).

Said fastest: **F2 makes it · F1 orders it · F3 is how you work it · F4 tells you honestly where you stand.**

## End-to-end architecture & UX

```mermaid
flowchart TD
    subgraph setup["SETUP (first run)"]
        Diag["Diagnostic: strong / rusty map"] --> Build["Set up study set:<br/>bundle + import + author seeds<br/>(AI off = raw; AI on = stylize + gap-fill)"]
    end
    Build --> Pool[("ONE topic-tagged, FSRS-scheduled pool")]
    subgraph study["STUDY"]
        Pool --> Sel["Layer-B selector (interleaving):<br/>worth × difficulty band × anti-block"]
        Sel --> Cards["Cards door (retrieval)"]
        Sel --> Probs["Problems door (+ wrong-answer ladder)"]
        ExamM["Exam mode (timed, no help)"]
    end
    Cards --> Log[("Attempt log, the spine")]
    Probs --> Log
    ExamM --> Log
    subgraph signals["SCORES (each honest: range + give-up rule)"]
        Log --> Mem["Memory: FSRS R"]
        Log --> Perf["Performance: P correct on a new Q"]
        Log --> Read["Readiness: projected score"]
        Mem --> Dash["Home + Progress:<br/>3 scores + model calibration"]
        Perf --> Dash
        Read --> Dash
    end
    Log -.->|"weighting feedback (near test)"| Sel
```

## Features × the three scores


|                             | Cards → Memory                                                        | Problems → Performance            | Exams → Readiness                         |
| --------------------------- | --------------------------------------------------------------------- | --------------------------------- | ----------------------------------------- |
| **Interleaving (F1)**       | orders due cards (topic-mixed)                                        | orders due problems (topic-mixed) | exams are inherently mixed                |
| **Forced generation (F2)**  | author conceptual seed → AI conforms/scales; CAS-checks computational | curated seed + AI-generated (feature-problem-generation.md)   | —                                         |
| **Productive failure (F3)** | —                                                                     | commit → ladder → consolidation   | exam = no help; ladder → post-exam review |
| **Calibration (F4)**        | FSRS R vs recall                                                      | predicted vs held-out Q           | score mapping + range                     |




## How they compose

```mermaid
flowchart TD
    Engine["Shared FSRS engine + Layer-B selector (Rust)"] --> Study["Study surface"]
    F2["F2 Forced generation (Content surface)"] -->|"makes cards + problems"| Study
    F1["F1 Interleaving (the selector)"] -->|"orders items in each door"| Study
    Study --> Cards["Cards door (memory)"]
    Study --> Probs["Problems door (performance)"]
    Probs --> F3["F3 Productive failure: commit → ladder → consolidation"]
    Cards --> Log[("Review / attempt log")]
    F3 --> Log
    Exam["Exam mode (readiness signal)"] --> Log
    Log --> F4["F4 Calibration: honest 3-score dashboard (Home / Progress)"]
    Log -.->|"drives next selection"| F1
```





## Reading the flow

- The **review/attempt log is the spine**: every card review, problem attempt, and exam feeds it; it drives the selector (F1), the scores (F4), and the consolidation (F3).
- **Ablation:** F1 (interleaving) is the single study feature tested full / off / plain-Anki.
- **AI-off (all four degrade gracefully):** F2 → authored/curated + reveal-and-self-compare; F3 → stored decompositions + self-compare; F4 → model calibration (no AI); F1 is pure engine logic.



## Baselines & AI-off (three distinct comparisons, don't conflate)

- **Ablation baseline (study feature, spec 5):** interleaving *full* vs *off* vs *plain Anki*, equal study time, metric pre-stated. "Off" means the selector is disabled (blocked order), not a reimplementation.
- **AI-quality baseline (spec 6):** AI generation must beat **keyword / vector search** over the same corpus, both scored on the gold set, side by side. The baseline is a simpler non-AI method doing the same job.
- **Works-with-AI-off (spec 7):** the whole app runs and produces scores with no AI at runtime, by graceful degradation (verified bundled content, FSRS, stored problem decompositions). It is not a parallel AI-off twin of every feature.

## Which POV / which doc

- F1 Interleaving (POV1) → `feature-interleaving.md`
- F2 Forced generation (POV2), cards → `feature-forced-generation.md`
- F2b Problem generation → `feature-problem-generation.md`
- F3 Productive failure (POV3) → `feature-productive-failure.md`
- F4 Calibration (POV4) → `feature-calibration.md`



## Build mapping (see `build-plan.md`)

- **F1 selector = L1** (the graded Rust change) · **F1/F3/F4 surfaces = L2** · **F2 + F3 tutor = L4** · **F4 models = L5**.

*Sources: the four feature docs; the project spec; the learning-science corpus.*