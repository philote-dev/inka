# pgrep (Physics GRE Speedrun)

**Exam: the Physics GRE (PGRE), scored 200 to 990.**

pgrep is a Physics GRE (PGRE) study app built by forking [Anki](https://apps.ankiweb.net). It ships a desktop app and an iOS companion on one shared engine, and reports what you can recall now (Memory), apply to a new problem (Performance), and would score today (Readiness) as three separate, honest numbers.

**What pgrep is, at a glance:**

- **One exam, done properly.** A focused prep app for the Physics GRE (100 five-choice questions in 170 minutes, scored 200 to 990), not a general flashcard tool.
- **Two apps, one engine.** A desktop app and an iOS companion share a single Rust study engine (a fork of Anki) and sync two-way.
- **Three honest scores.** Memory, Performance, and Readiness stay separate, each with an 80% range and a give-up rule. The app abstains ("not enough yet") instead of inventing a number.
- **AI is optional.** Both apps build, study, and score with AI switched off. AI only adds card and problem generation, each citing a named source or refusing.

This README is a quickstart for building, running, and testing the app. The full design, the score math, the AI layer, and the held-out evaluation live in the paper and in [`docs_pgrep/`](docs_pgrep/README.md).

## Paper

The full write-up covers the design rationale, the three-score model, the AI item layer, and the reproducible held-out evaluation, with the negatives reported alongside the wins. The paper is **[pgrep: A Physics GRE Preparation System with Separated, Calibrated Readiness Scores](docs_pgrep/paper/main.pdf)**, by Frank Gonzalez (July 2026). GitHub renders the [PDF](docs_pgrep/paper/main.pdf) in the browser. The source is [`main.tex`](docs_pgrep/paper/main.tex) with [`references.bib`](docs_pgrep/paper/references.bib).

## Build and run

Every build, run, test, and lint step is a `just` recipe. Run `just --list` for the full set. Both apps run with AI off and still produce scores.

```bash
# Desktop
just run            # build pylib + qt and launch the desktop app (AI off)
just run-optimized  # release-optimized build

# Desktop with AI (optional, off by default, never required to build/study/score)
just pgrep-ai-deps  # one-time: install the optional AI deps into out/pyenv
just run-ai         # build + run with OPENAI_API_KEY (from the env or content/.env)

# Self-hosted sync (reuses Anki's sync engine unmodified)
just sync-server    # defaults to port 8090

# iOS companion (macOS only)
just ios-run        # build the FFI, regenerate the Xcode project, launch the Simulator

# Format + build + all lints and tests (Rust, Python, TypeScript)
just check
```

Desktop web surfaces are served during development at `http://localhost:40000/_anki/pages/`.

## Testing the submission, feature by feature

Everything runs locally through `just`. Each feature notes where it lives and the command that exercises it; deeper detail is in the paper and the linked docs. The on-camera steps are in [`docs_pgrep/reference/recording-guide.md`](docs_pgrep/reference/recording-guide.md) and the full checklist in [`docs_pgrep/proofs/submission-proofs.md`](docs_pgrep/proofs/submission-proofs.md).

Run everything once with `just check` (all lints and tests, green).

- **Rust engine change (points-at-stake selector).** Lives in `rslib/src/scheduler/queue/builder/points_at_stake.rs` and reorders due cards by exam value in memory only, mutating no scheduling state. Run `just test-rust` and `just test-py` for its 11 Rust and 2 Python tests. Files touched and merge difficulty are in the paper and [`docs_pgrep/research/anki-rooting-and-rust.md`](docs_pgrep/research/anki-rooting-and-rust.md).
- **Three scores (Memory, Performance, Readiness).** Live in `pylib/anki/pgrep/{memory,performance,readiness,coverage}.py`. Run `just test-py`, or `just run` and open Home (three cards with ranges) and Progress (coverage plus calibration diagrams). A fresh account honestly abstains on all three.
- **Study feature (interleaving, ablation-tested).** The points-at-stake selector above, with the harness and results in the private `content/` workspace. It beats the blocked variant in every configuration but loses to plain Anki at 10 reviews per day (see [known limitations](#known-limitations)).
- **AI generation and safety.** Run `just eval-public` (offline, no key) for the metrics, baselines, and leakage firewall. The AI-off path is proven by `pylib/tests/test_pgrep_problem_gen.py::test_ai_off_session_imports_no_heavy_deps`. Detail in [`docs_pgrep/ai/ai-layer.md`](docs_pgrep/ai/ai-layer.md).
- **Two apps, one engine, with sync.** Run `just ios-sync-proof` and `python -m pytest pylib/tests/test_pgrep_sync_roundtrip.py`. A phone review appears on the desktop after a two-way sync.
- **Runs with AI off.** `just run` (desktop) and the iOS default build, study, and score with no key present.
- **Speed and crash-safety.** `just bench --cards 50000` for latency against targets, and `just crash-test` for 20 mid-review kills with no corruption or lost reviews.
- **Installers and clean-device runs.** Build, sign, and distribution steps are in [`docs_pgrep/reference/installer-and-distribution.md`](docs_pgrep/reference/installer-and-distribution.md).

## Architecture

One shared engine, surfaced two ways, so desktop and phone never disagree about a card, a review, or a score.

- **Shared Rust engine (`rslib/`).** FSRS memory model, the queue builder (with the pgrep selector), SQLite storage, and Anki's sync. The single source of truth for both apps.
- **Desktop (`qt/` and `ts/routes/pgrep/`).** A PyQt shell hosts Svelte/TypeScript surfaces that call pure-Python `anki.pgrep.*` functions over a small JSON bridge (`qt/aqt/pgrep.py`). Scores are computed in Python over engine state, with no AI on the scoring path.
- **iOS (`mobile/ios/PgrepStudy/`).** Native SwiftUI over the same engine through a C FFI (`rslib/ffi/`, packaged as `out/ios/AnkiFfi.xcframework`).

Full detail is in the paper and [`docs_pgrep/research/technical-architecture.md`](docs_pgrep/research/technical-architecture.md).

## Known limitations

Honest negatives count as results. Detail is in the paper and [`docs_pgrep/ai/ai-layer.md`](docs_pgrep/ai/ai-layer.md).

- **AI generation** cites a source or refuses, and beats every baseline (keyword, vector, and naive-distractor, all with confidence intervals excluding zero), but does not clear all pre-registered absolute cutoffs (card fact-precision about 0.90 vs 0.95, problem key-correctness about 0.69 vs 0.95). The leakage firewall is green.
- **The study-feature ablation** is a simulation (synthetic learners, n=1), not a human trial. The selector beats the blocked variant everywhere but loses to plain Anki at 10 reviews per day.
- **The iOS app** is a review, scores, and sync companion on the shared engine, being extended toward full desktop parity.

## Documentation and repository layout

- **[`docs_pgrep/`](docs_pgrep/README.md)** is the documentation root (spec, research, plan, contracts, reference, ai, proofs).
- **Spec (the assignment):** `docs_pgrep/spec/Speedrun_ A Desktop + Mobile Study App Built on Anki.pdf`.
- **Paper (the write-up):** [`docs_pgrep/paper/main.pdf`](docs_pgrep/paper/main.pdf).
- **Three score models:** `pylib/anki/pgrep/{memory,performance,readiness,coverage}.py`, documented in [`three-scores.md`](docs_pgrep/research/three-scores.md).
- **Engine change:** `rslib/src/scheduler/queue/builder/points_at_stake.rs`, documented in [`anki-rooting-and-rust.md`](docs_pgrep/research/anki-rooting-and-rust.md).
- **Build proofs:** [`docs_pgrep/proofs/`](docs_pgrep/proofs/).

## License and credits

pgrep is a fork of [Anki](https://github.com/ankitects/anki) by Ankitects Pty Ltd and contributors, and keeps Anki's license, the **GNU Affero General Public License, version 3 or later (AGPL-3.0-or-later)**, with portions contributed by Anki users under the **BSD-3-Clause** license. See [LICENSE](./LICENSE) and [CONTRIBUTORS](./CONTRIBUTORS). All credit for the underlying spaced-repetition engine, scheduler, and sync belongs to the Anki project. pgrep adds the PGRE selector, scores, surfaces, and mobile companion on top of it.
