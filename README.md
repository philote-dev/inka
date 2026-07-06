# pgrep (Physics GRE Speedrun)

**Exam: the Physics GRE (PGRE), scored 200 to 990.**

pgrep is a study environment for one graduate-level exam, the Physics GRE, built by forking [Anki](https://apps.ankiweb.net). It ships a desktop app and a phone companion that share one engine, and it answers three different questions honestly rather than blending them into one flattering number: can you recall a fact now (Memory), can you apply it to a new exam-style problem (Performance), and what would you score today (Readiness). Its reason to exist is the memory to performance to readiness bridge that stock flashcards lack, because the PGRE is problem-solving-heavy and fact-recall-light, so it measures the gap between remembering a card and answering a novel question, and it refuses to show a score when the evidence is too thin.

This README is the submission entry point. It states the exam, the build and run steps for both apps, the architecture, the engine change, the upstream files touched, and the three score models with their give-up rules. It closes with an honest account of what does and does not clear its own bars.

## The exam: PGRE

pgrep models the real, modern Physics GRE as the shipped code does (see `pylib/anki/pgrep/exam.py` and `pylib/anki/pgrep/readiness_constants.py`):

- **100 scored, five-choice multiple-choice questions in 170 minutes** (about 1.7 minutes per question).
- **Formula scoring with a one-quarter-point penalty per wrong answer**: `raw = round(correct - incorrect / 4)`. Skipped questions carry no penalty.
- **Scaled score 200 to 990**, in 10-point steps, via the official raw-to-scaled conversion table (embedded as numeric constants only).
- The official report is a single total score. pgrep additionally breaks results down per blueprint category to drive coverage and the next-best-topic suggestion, but it does not invent separately reported subscores.

**Blueprint (stable for 20+ years), used verbatim by both the Rust selector and the Python scores:** Mechanics 20%, Electromagnetism 18%, Quantum 13%, Thermodynamics and Statistical Mechanics 10%, Atomic 10%, Optics and Waves 8%, Special Relativity 6%, Lab Methods 6%, Specialized 9%.

## Build and run (both apps)

Every build, run, test, and lint step is a `just` recipe. Run `just --list` to see them all. Both apps run with AI switched off and still produce scores.

### Desktop

```bash
just run            # build pylib + qt and launch the desktop app
just run-optimized  # release-optimized build
```

Web surfaces are served during development at `http://localhost:40000/_anki/pages/`.

### Desktop with AI enabled (optional)

AI is off by default and is never required to build, study, or score. To enable live card and problem generation and the scaffold-fade tutor:

```bash
just pgrep-ai-deps  # install the optional AI runtime deps into out/pyenv (one time)
just run-ai         # build + run with an OpenAI key from the env or content/.env
```

`just run-ai` refuses to start without `OPENAI_API_KEY`, and the in-app toggle keeps AI opt-in.

### Self-hosted sync

```bash
just sync-server    # run a self-hosted Anki sync server (defaults to port 8090)
```

This reuses Anki's own sync engine unmodified. Nothing under `rslib/src/sync/` changes.

### iOS companion (macOS only)

```bash
just ios-run         # build the FFI, regenerate the Xcode project, launch in the Simulator
just ios-smoke       # build the xcframework and run the iOS Simulator XCTest
just ios-sync-proof  # prove the FFI sync path end to end (phone to server to desktop)
```

`just ios-xcframework` builds the shared engine as `out/ios/AnkiFfi.xcframework` on its own.

### Full checks

```bash
just check          # format, then build and run lints and tests (Rust, Python, TypeScript)
```

Use `just check` as the final step before treating a change as done. Language-specific runners are `just test-rust`, `just test-py`, and `just test-ts`.

## Architecture overview

pgrep is one shared engine surfaced two ways. The scheduler, storage, sync, FSRS memory model, and all three scores run in one place, so the desktop app and the phone companion can never disagree about a card, a review, or a number.

- **Shared Rust engine (`rslib/`).** The core spaced-repetition engine, the queue builder (including the pgrep review-card selector), the FSRS retrievability primitive the scores reuse, SQLite storage, and Anki's sync. This is the single source of truth for both apps.
- **Desktop (Qt + TypeScript over the engine).** The PyQt shell embeds Svelte/TypeScript surfaces (`ts/routes/pgrep/`: home, study, the two study doors, timed exam, progress, library, diagnostic, settings). Those surfaces talk to the engine through a small JSON bridge, `qt/aqt/pgrep.py`, where each handler is a `mediasrv` POST endpoint that calls a pure-Python `anki.pgrep.*` function on the collection. The three scores are computed in Python over engine state, with no AI on the scoring path.
- **iOS (native SwiftUI over the same engine via C FFI).** A thin C ABI in `rslib/ffi/` exposes Anki's backend so a SwiftUI app drives the exact same Rust engine desktop uses, packaged as `out/ios/AnkiFfi.xcframework`. The companion (`mobile/ios/PgrepStudy/`) runs real review sessions, shows the scores, and syncs two-way. Because the engine is shared, the Rust selector change below ships to the phone too.

## The Rust engine change: the points-at-stake review selector

The graded engine change lives in `rslib/src/scheduler/queue/builder/points_at_stake.rs`.

**What it does.** It adds a new review order, `ReviewCardOrder::PointsAtStake`. Stock Anki orders due reviews with an SQL `ORDER BY` at gather time and applies the daily review limit during that SQL iteration, so a naive post-sort would arrive after the limit already cut the high-value cards. The change is therefore a genuine gather-then-limit pass: for a points-at-stake deck the gather step collects all non-buried due reviews, then this module scores each one, reorders within the due set, and truncates to exactly the daily limit stock Anki would have applied. A card's worth is `blueprint%(topic) times weakness(topic)`, where `weakness = 1 - mean FSRS retrievability over that topic's due cards`, adjusted by a desirable-difficulty band factor (retrievability 0.60 to 0.85 preferred). A K=3 anti-blocking pass then shapes the emit order so no more than three consecutive cards share a category, without ever dropping a higher-worth card. It only reorders an in-memory vector. It never mutates `due`, `interval`, or `memory_state`, never writes collection data, and never creates an undo entry, so scheduling, undo, and sync are untouched.

**Why it belongs in Rust, not Python.** The ordering and the daily limit are enforced together inside the engine's gather loop. The limit is applied as the SQL is iterated, so the only way to order by a value the SQL cannot express, and still respect the exact limit and sibling-burying rules, is to change the gather-and-limit path itself. Doing it in Python after the fact would either see a list the limit had already truncated, or would require re-implementing limits, burying, and cross-deck accounting outside the engine. Keeping it in Rust also means the change ships to the phone through the same shared engine, at no extra cost.

**Its tests: 11 Rust and 2 Python.**

- 6 Rust unit tests in `points_at_stake.rs`: tag and category parsing, band boundaries, the worth-and-band scoring, anti-blocking run caps, in-band preference at equal worth, and worth-ordered truncation.
- 5 Rust integration tests in `rslib/src/scheduler/queue/builder/mod.rs`: end-to-end worth ordering that also proves the build mutates no card, the review-limit and shared new-card cap interaction, an eligible cross-deck sibling that must not be pre-buried, same-note sibling burying under the new order, and truncation by worth before anti-blocking.
- 2 Python tests: `pylib/tests/test_pgrep_selector.py` drives the v3 scheduler through `get_queued_cards` and asserts the returned order reflects worth (an untagged card sorts last but is never dropped), and `pylib/tests/test_pgrep_seed.py` asserts the seeded deck is set to the points-at-stake order.

Run them with `just test-rust` and `just test-py`.

## Upstream Anki files touched, and merge difficulty

The engine change is deliberately small and additive. Measured against the upstream Anki merge-base, it is roughly 974 insertions with no deletions across the engine, plus 3 lines in pylib.

| File                                                   | Nature of the change                                                                      | Approx. size        |
| ------------------------------------------------------ | ----------------------------------------------------------------------------------------- | ------------------- |
| `proto/anki/deck_config.proto`                         | Add one enum value, `REVIEW_CARD_ORDER_POINTS_AT_STAKE = 13`, with a comment              | +6                  |
| `rslib/src/storage/card/mod.rs`                        | One match arm giving the new variant a neutral SQL gather order                           | +5                  |
| `rslib/src/scheduler/queue/builder/gathering.rs`       | One branch: for the new variant, gather all due reviews and defer the limit to the scorer | +26                 |
| `rslib/src/scheduler/queue/builder/mod.rs`             | Register the new module and add the 5 integration tests                                   | +362 (mostly tests) |
| `rslib/src/scheduler/queue/builder/points_at_stake.rs` | New standalone scorer module (the change plus 6 unit tests)                               | +575 (new file)     |
| `pylib/anki/collection.py`                             | One small backend seam-check method                                                       | +3                  |

The proto and Python bridge are code-generated from the `.proto` files during `just check`, so no generated files were hand-edited.

**Merge difficulty: low.** The footprint is additive. The proto change appends a new enum value (13) without renumbering existing variants. The engine touches are a single match arm and a single gather branch, and the scorer is an isolated new file, so a routine upstream pull will not conflict with it. The realistic conflict surfaces are narrow: upstream claiming enum value 13 for a different review order, or a refactor of `review_order_sql` or the gather seam in `gathering.rs`. Either would be a small, localized rebase. This estimate is honest and approximate, derived from the diff against the merge-base, not a guarantee about future upstream churn.

## The three scores (each with a give-up rule)

All three scores are pure math over FSRS state and the attempt log, with no AI on the scoring path, so both apps score with AI off. Every score carries a point, an 80% range, a coverage figure, and an abstain rule. Detail lives in `docs_pgrep/research/three-scores.md`.

**Memory, P(recall now).** The blueprint-weighted expected fraction of your reviewed cards you would recall right now. Per card it reuses the engine's own FSRS retrievability (the same primitive the selector uses, so the score and the selector never disagree); new or unreviewed cards are excluded. Per topic it reports `mean(R)` with a Poisson-binomial 80% range. **Give-up rule:** a topic with fewer than `k_mem` (5) reviewed cards shows "Not enough cards yet" instead of a number, and the overall score abstains when no topic qualifies.

**Performance, P(correct on a new question).** The probability of getting a novel, unseen exam-style problem right, per topic. This is transfer, not recall, so it is computed from the attempt log using Performance Factors Analysis, a calibrated logistic over topic mastery (the memory bridge, read from the same FSRS primitive), authored item difficulty, and recent successes and failures, with beta calibration. Only clean, committed, first-try attempts count; laddered or rapid-guess attempts are filtered out. **Give-up rule:** a topic abstains until it has at least `k_perf` (8) clean attempts and its 80% interval is tighter than 0.40. With an empty attempt log every topic abstains, which is the correct behavior today.

**Readiness, the projected scaled score.** The projected PGRE scaled score (200 to 990) with an explicit 80% range. It leans on Performance, not Memory, because the exam measures transfer. Each topic contributes its blueprint share of the 100 questions at its Performance probability; the total-correct is a Poisson-binomial whose mean and range are mapped through the official raw-to-scaled table, combining sampling spread with the model spread carried by each topic's Performance interval. **Give-up rule:** Readiness shows no scaled score until coverage, the blueprint-weighted fraction of topics with at least `k_perf` scored attempts, reaches the 70% gate. Below the gate it abstains, says "Not enough of the exam is covered yet," and names the uncovered topics. A covered-but-imprecise topic falls back to the guessing baseline and is surfaced separately so it cannot quietly help clear the gate.

Coverage itself (`pylib/anki/pgrep/coverage.py`) is the honest ledger underneath: a category is covered once it has at least one reviewed card, and the overall figure is the summed blueprint weight of covered categories.

## Submission status and known limitations

The spec rewards honest numbers over flattering ones, and honest negatives count as results. The following are reported as such.

**The AI generation gate passes provenance and beats every baseline, but does not fully clear the absolute preset cutoffs.** Cutoffs were pre-registered and frozen before results were seen (`docs_pgrep/ai/cutoffs-and-baselines.md`). Under the human adjudicator of record, generated cards clear useful-yield (0.84 against a 0.80 bar) but miss fact-precision by one step (about 0.90 against the 0.95 target, five cards carried a fact slip). Generated problems fall short on the absolute bars: key-correctness is about 0.69 against a 0.95 target, distractor quality about 0.67 against 0.70, and useful-yield about 0.64 against 0.75. The shipped, non-refused problems are strong (key 1.00, useful 0.92, distractors 0.96 by the human), but a roughly 31% refusal rate drags the batch under the bars, so the remaining work is generation hardening, not a gold-set or methodology problem. Every output still cites a named source or is refused, the AI beats keyword and vector retrieval (by about +0.74 on cards and +0.67 on problems) and beats naive-distractor generation (about +0.42), all with bootstrap confidence intervals excluding zero, and the leakage firewall is green. Detail in `docs_pgrep/ai/ai-layer.md`.

**The study-feature ablation is a simulation, not a human trial, and it reports a real negative.** The interleaving selector was tested with a pre-registered outcome across three builds (full, feature-off, and plain Anki) on synthetic learners at n=1 (`content/run/ablation.md`), not a human study. The interleaved (full) build beats the blocked variant in all six configurations (small but consistent, confidence intervals exclude zero). Against plain, unmodified Anki it wins at 20 and 30 reviews per day but loses at 10 reviews per day, an explained difficulty-band trade-off at the scarcest budget. The K=3 anti-blocking is memory-neutral by construction. So the feature does not robustly beat stock Anki at every budget, and that is reported plainly rather than hidden.

**The iOS app is a review, scores, and sync companion, currently being extended toward parity.** It runs real review sessions on the shared Rust engine through the C FFI, shows the three scores, and syncs two-way with the desktop (see `just ios-sync-proof`). It is a companion by design and is being extended toward fuller desktop feature parity, not yet a full mirror of the desktop surfaces.

For context on where the memory and performance models do stand: Memory is calibrated on a held-out review set and beats a base-rate baseline on the primary Brier score, and Performance passes its pre-registered beat-baseline rule on held-out synthetic data while being honest that synthetic validates the pipeline, not a real cohort, at n=1.

## Documentation and repository layout

- **`docs_pgrep/`** is the project documentation root, grouped by purpose (spec, research, plan, contracts, reference, ai, proofs). Start at `docs_pgrep/README.md`.
- **The governing spec** is `docs_pgrep/spec/Speedrun_ A Desktop + Mobile Study App Built on Anki.pdf`.
- **The three score models** are `pylib/anki/pgrep/{memory,performance,readiness,coverage}.py`, documented in `docs_pgrep/research/three-scores.md`.
- **The engine change** is `rslib/src/scheduler/queue/builder/points_at_stake.rs`, documented in `docs_pgrep/research/anki-rooting-and-rust.md`.
- **Build proofs** (clean build, tests, installer, phone smoke, sync) are under `docs_pgrep/proofs/`.

## License and credits

pgrep is a fork of [Anki](https://github.com/ankitects/anki) by Ankitects Pty Ltd and contributors, and it keeps Anki's license. The project is distributed under the **GNU Affero General Public License, version 3 or later (AGPL-3.0-or-later)**, with portions contributed by Anki users under the **BSD-3-Clause** license. See [LICENSE](./LICENSE) for the full terms and [CONTRIBUTORS](./CONTRIBUTORS) for the list of contributors. All credit for the underlying spaced-repetition engine, scheduler, and sync belongs to the Anki project; pgrep adds the PGRE-specific selector, scores, surfaces, and mobile companion on top of it.
