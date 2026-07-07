# Literature Synthesis (Phase 1)

The report provides its own sources, so this phase goes directly to synthesis rather
than search. Sources are drawn from the evidence tables and source footers already
compiled across `docs_pgrep/research/*`. Citations marked `[verify]` need a DOI and
exact-figure check before any external submission (several reached the project through
summary notes). Nothing here is fabricated; unverified items are flagged, not invented.

The synthesis is organized by the seven evidence themes that map onto pgrep's design,
under one organizing frame.

## Organizing frame: learning is not performance

Soderstrom and Bjork (2015) separate _learning_ (durable, transferable change) from
_performance_ (what you can do right now). This is the report's spine: it justifies
three separate scores rather than one, and it warns against optimizing in-session
accuracy. Everything below attaches to this frame.

## Theme 1: Spaced repetition and memory models

- FSRS (the DSR three-component model; Ye et al.) is the deployed memory model in the
  reused engine. On the public srs-benchmark (about 10k users, 727M reviews,
  time-split), FSRS-6 reports log-loss 0.346, RMSE 0.065, AUC 0.70, beating HLR and a
  simple average baseline. `[verify exact benchmark figures]`
- SM-2 (the classic Anki heuristic) is the dated fallback: interval times an ease
  factor, not probability-calibrated.
- HLR (Settles and Meeder, 2016, ACL/Duolingo): half-life regression, about 45 percent
  error reduction over baselines. Underperforms FSRS on srs-benchmark. `[verify]`
- MEMORIZE (Tabibian et al., 2019, PNAS) and SSP-MMC / DHP (Ye, Su and Cao, 2022, KDD):
  spaced repetition as stochastic optimal control and as a stochastic shortest path;
  FSRS's direct ancestors.

Design consequence: pgrep reuses FSRS for Memory and never reimplements scheduling. Its
own work sits in _selection_ (Layer B), not scheduling (Layer A).

## Theme 2: Interleaving and desirable difficulty

- Physics: Samani and Pan (2021, npj Science of Learning): mixed versus blocked homework
  raised surprise novel-problem test scores by 50 to 125 percent. `[verify]`
- Math: Rohrer and Taylor (2007); Taylor and Rohrer (2010, spacing held fixed,
  interleaving doubled next-day scores); Rohrer, Dedrick and Burgess (2014, grade 7,
  72 vs 38 percent, d about 1.05). `[verify]`
- Meta: Firth, Rivers and Boyle (2021), g about 0.5 to 0.65, largest when concepts are
  confusable. Sana and Yan (2022), d about 0.35 at delay. `[verify]`
- Kornell and Bjork (2008): interleaving beats massing and learners misjudge it (a
  metacognitive illusion).
- Mechanism (Rohrer, 2014): interleaving forces choosing the strategy from the problem
  itself, training discrimination, exactly the PGRE skill.
- Desirable difficulty: Bjork's desirable difficulties; the region of proximal learning
  (Metcalfe); the 85 percent rule (Wilson et al., 2019, derived for classifier training,
  applied with stated assumptions). `[verify]`

Design consequence: the selector interleaves topics within a door and prefers a 60 to 85
percent predicted-success band. The ablation's blocked arm operationalizes the
massed-versus-spaced contrast.

## Theme 3: The generation effect

- Slamecka and Graf (1978): self-generated material is remembered better than read,
  even when identical. Meta d about 0.40 (Bertsch et al.). `[verify]`
- Pan, Wendt et al. (2022, APA), six experiments: user-generated versus premade
  flashcards, memory d about 0.45, application d about 0.29. `[verify exact numbers]`

Design consequence: AI card generation is "pay to play." The learner authors a
conceptual seed first (the generative act), then AI stylizes or gap-fills. Import adds
breadth but never substitutes for authoring.

## Theme 4: Productive failure, scaffolded struggle, and AI tutoring

- Kapur (2008, 2016): struggle before instruction aids delayed transfer; consolidation
  afterward is mandatory. Kalyuga (expertise reversal): heavy guidance backfires as
  prior knowledge grows, so pgrep uses attempt-before-help on already-known concepts and
  fast fading, not classic pre-instruction PF.
- Bastani et al. (2025, PNAS, about 1,000-student RCT): unguarded GPT access reduced
  learning; guardrailed access matched human tutors. Qian et al. (2026): 40 percent-plus
  of AI hints solved the task for the student (leakage). `[verify]`
- Chi (self-explanation): the learner must produce the explanation. Sweller (CLT,
  completion problems). Renkl and Atkinson (worked example to completion to full
  problem, adaptive fading). Roediger and Karpicke (even failed retrieval helps with
  feedback). Gjerde (2022, PRPER): retrieving principles before problems improves
  problem solving, d about 0.4. `[verify]`
- Tutoring engineering: the LLM Hint Factory's progressive specificity; StAP-tutor
  (2024, one next step at a time, no solution in the prompt); Phung et al. (2024, LAK):
  generate then simulated-student validate then retry lifts precision from 60 to 66
  percent up to 94 to 98 percent. `[verify]`

Design consequence: the wrong-answer ladder (nudge, sub-goal decomposition and
self-explanation, sibling worked example, reveal and explain-back) over a stored,
verified decomposition, with a giveaway verifier so the final answer never leaks and an
AI-off reveal-and-self-compare path.

## Theme 5: Performance modeling and knowledge tracing

- PFA (Pavlik, Cen and Koedinger, 2009) and AFM (Cen, Koedinger and Junker, 2006):
  logistic models predicting correctness from skill mastery, item difficulty, and prior
  success/failure counts. R-PFA (Galyardt and Goldin, 2014): recent history carries most
  of the signal. PFA beats Bayesian Knowledge Tracing head to head (Gong, Beck and
  Heffernan, 2011). `[verify]`
- BKT (Corbett and Anderson, 1994/1995): HMM per skill; identifiability issues. DKT
  (Piech et al., 2015) and AKT (Ghosh et al., 2020): neural, data-hungry, opaque; no
  advantage at this scale.
- IRT floors: with one learner, item difficulty and ability are jointly unidentifiable
  (Lord, 1980; Embretson and Reise, 2000); IRT/Rasch needs about 100 to 200 examinees
  per item (Rasch, 1960; Lord and Novick, 1968). `[verify]`

Design consequence: Performance is a PFA calibrated logistic over four interpretable
features (mastery, difficulty, recent successes, recent failures), with the base-rate
batting average kept as the baseline to beat, and in-house IRT rejected at n=1.

## Theme 6: Calibration and honest uncertainty

- Proper scores and calibration: Brier (1950); DeGroot and Fienberg (1983); modern
  calibration metrics and reliability diagrams (Guo et al., 2017). `[verify]`
- Post-hoc calibration: Platt (1999); Zadrozny and Elkan (2002); beta calibration (Kull
  et al., 2017, the locked choice for small data); Venn-Abers (Vovk, deferred). Isotonic
  avoided at small n.
- Interval math: Wilson (1927) and Beta-Binomial conjugacy (Gelman et al., BDA) for
  proportions; the Poisson-binomial (Le Cam) for sums of unequal Bernoullis (Memory
  fraction, Readiness raw). `[verify]`
- Validity and leakage: McNemar (1947) for the paired paraphrase bridge test; Kapoor and
  Narayanan (2023) on leakage in ML-based science; sample-size floors for logistic
  models (Peduzzi, 1996; van Smeden et al., 2019) and interval-based stopping (Brown,
  Cai and DasGupta, 2001). `[verify]`

Design consequence: every score ships an 80 percent central interval and an abstain
rule; calibration is measured with Brier (primary), log-loss, ECE, and a reliability
diagram on time-based held-out splits.

## Theme 7: AI generation with provenance and honest evaluation

- Grounding and verification: RAG grounding with source binding and verbatim anchors;
  CAS/symbolic checking (SymPy, the PAL pattern) for computational items;
  self-consistency; independent-critic weakness (self-critics rubber-stamp).
- Distractors: misconception-first generation (name the likely error, derive the trap)
  as the education-measurement norm; a student-selection-data ranker deferred as the
  frontier. `[verify cohort claims]`
- Evaluation discipline: the gold-set gate with a pre-registered cutoff; a named baseline
  the AI must beat (keyword and vector retrieval); time-based held-out splits; a written
  leakage rule. This mirrors the report's own methodology and the reproducibility norm
  in ML evaluation (Kapoor and Narayanan, 2023).

Design consequence: the AI layer cites a named open-corpus source or refuses; a gold-set
gate with frozen cutoffs and keyword/vector baselines governs shipping; a structural plus
guarded leakage firewall keeps held-out and gold items out of the corpus, index, and
every prompt.

## What the literature does and does not license (honesty boundary)

- It licenses the _mechanisms_ (interleaving, generation, scaffolded struggle,
  calibration) and the _modeling choices_ (FSRS for memory, PFA for performance, beta
  calibration).
- It does not license a claim of a measured human learning gain for pgrep specifically.
  The n=1 setting means the ablation validates the shipped mechanism under an FSRS
  ground truth, and the Performance model is validated on seeded synthetic data. The
  report states this boundary wherever it reports a number.
