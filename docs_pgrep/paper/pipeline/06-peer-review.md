# Peer Review and Revision (Phase 6)

Simulated double-blind review across the skill's five dimensions, then the revisions
applied. Two rounds maximum; unresolved items become acknowledged limitations. Copy
rule applies.

## Round 1 findings

Machine checks first, then the five dimensions.

**Automated checks.**

- Compilation: clean (pdflatex + bibtex via latexmk), no errors.
- Citations: 6 orphans found (defined but uncited): corbett1994, piech2015,
  gelman2013, mcnemar1947, wilsoninterval1927, phung2024.
- Copy rule: 0 em-dashes, 0 stray en-dashes.
- Anti-patterns: none of the flagged AI-tell phrases present.
- Word count: about 5,000, under the 7,500 target by more than 10 percent.

**Originality (20%).** Strong for a systems report. The novelty is the composition:
an in-engine exam-value selector, three separated and calibrated scores, a
provenance-gated AI item layer, and a held-out evaluation, integrated in one product.
No change needed.

**Methodological rigor (25%).** Strong. Held-out time-based splits, pre-registered
cutoffs, a leakage firewall, a named baseline, and bootstrap intervals are all present
and correctly described. The n=1 boundary is stated wherever a number appears. Minor:
the evaluation methodology could state the two-rater blind process and the
equal-study-time control explicitly.

**Evidence sufficiency (25%).** Adequate and honest. Every headline number traces to a
recorded artifact, and the negatives (synthetic Performance, the tight-budget ablation
loss, the two short AI cutoffs, near-zero judge agreement) are reported. Bounded by
n=1, which is acknowledged rather than hidden.

**Argument coherence (15%).** Good. The learning-not-performance frame threads through
the whole report, and the honesty-by-construction through-line ties the discussion
together.

**Writing quality (15%).** Good and compliant with the house style. The early sections
under-cite the literature relative to the material available, and several mechanisms
are compressed.

## Revisions applied

Round 1 revisions, all completed and recompiled clean.

1. **Citation hygiene.** Cited the three orphans that fit the argument (corbett1994 and
   piech2015 in the Performance section as knowledge-tracing alternatives, gelman2013
   for the partial-pooling interval). Removed the three whose methods are not used in
   the reported results (mcnemar1947, wilsoninterval1927, phung2024). Final state: 45
   references, all cited, none undefined, none orphaned.
2. **Literature in the early sections** (per Frank's request). Added effect sizes and
   specifics to the interleaving, generation-effect, and productive-struggle
   paragraphs, so the Background carries the evidence rather than gesturing at it.
3. **Length and depth.** Expanded from about 5,000 to about 7,000 words with real
   content, not padding: an architecture and data-model subsection, the selector's
   caching and the deferred readiness-aware weighting, the three-score design
   principles, the AI verification stack and the fed-versus-held data split, the
   evaluation's two-rater and reproducibility process, the generator hardening and
   reject-memorized detail, the sync conflict rule, and discussion paragraphs on the
   data-model payoff, the relationship to the reused tool, and future work.
4. **Small clarity additions.** A concrete Memory-versus-Performance example in the
   introduction, the misconception taxonomy note, the interval-widening behavior of
   Readiness, and the simulation's assumptions in Limitations.

## Round 2

No blocking issues remained after round 1. The report compiles clean, citations are
matched, the copy rule holds, and the length is in band.

## Acknowledged limitations (carried, not fixable in review)

- The evaluation is single-learner; Performance is validated on synthetic data and the
  ablation is a simulation. Stated in the paper.
- Citation metadata (DOIs, a few exact figures) needs a verification pass before any
  external use. Stated in the paper's limitations and the bibliography header.

## Decision

Accept. The revisions above were applied in Phase 6 and the paper recompiled to a clean
16-page PDF.
