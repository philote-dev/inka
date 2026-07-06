# pgrep - Submission Proofs (Sunday)

Physics GRE prep, forked from Anki. This is the master list of everything to
show for the final submission: the demo video shots, the terminal evidence, and
the clean-device install clips. It maps each spec area to its proof and marks
what is already proven versus what you still need to record.

**Commit:** `0fa523f68`, verify live with `git rev-parse HEAD`

Legend: [PROVEN] runs now and passes, [RECORD] a clip you capture, [HONEST] a
documented honest result or known limitation.

Setup for the whole demo: `just sync-server` (port 8090, pgrep/pgrep) and
`just run-ai` for the desktop, `just ios-run` for the phone. Inject the demo
account from the dev lab (`http://127.0.0.1:40000/pgrep-lab`, Demo control) so
the scores light up. Full recording steps: `docs_pgrep/reference/recording-guide.md`.

## What to hand in (spec section 12)

- Public AGPL fork, exam stated up front, build instructions for both apps,
  architecture, the Rust-change note, files touched: `README.md`. [PROVEN]
- Demo video, 3 to 5 minutes: record per `recording-guide.md`. [RECORD]
- Model descriptions with give-up rules: `README.md` plus
  `docs_pgrep/research/three-scores.md`. [PROVEN]
- Brainlift: yours. [RECORD]

## 1. Rust engine change (20%)

A new review order `ReviewCardOrder::PointsAtStake` in
`rslib/src/scheduler/queue/builder/points_at_stake.rs`: it reorders the due set
by blueprint weight times topic weakness in memory only, never mutating `due`,
`interval`, `memory_state`, undo, or sync. 11 Rust tests + 2 Python tests.

```
just test-rust        # points_at_stake unit + integration tests
just test-py          # includes pylib/tests/test_pgrep_selector.py + test_pgrep_seam.py
```

[PROVEN] Show the tests passing and open `points_at_stake.rs`. Files touched and
the merge-difficulty note are in `README.md`. [RECORD] one line on camera.

## 2. Three scores with honest uncertainty (20%)

Memory, Performance, Readiness, each with a point, an 80% range, a how-sure read,
coverage, last-updated, and a give-up rule. Coverage gates Readiness at 70%.

- Backends: `pylib/anki/pgrep/{memory,performance,readiness,coverage}.py`.
- Tests: `test_pgrep_{memory,performance,readiness,coverage}.py` (via `just test-py`).
- Calibration reliability diagrams: Progress tab, from
  `pylib/anki/pgrep/calibration_evidence.py`.

[RECORD] Home (three cards with ranges), then the Progress tab (coverage bar,
calibration diagrams). [PROVEN] Honesty: a fresh account abstains on all three
("not enough yet"); no number is fabricated.

## 3. Study feature, ablation-tested (15%)

Interleaving via the points-at-stake selector, tested with three arms (full,
blocked, plain Anki) at equal study time, pre-registered metric BWER.

- Harness and results: `content/tools/ablation.py`, `content/run/ablation.md`.

[HONEST] The full selector beats the blocked variant everywhere (CI excludes
zero) but loses to plain Anki at 10 reviews per day, and the study is a
simulation (n=1 synthetic), not a human trial. Report this negative on camera;
a fair test that could fail scores well.

## 4. AI checking and safety (15%)

Every AI output cites a named source or is refused; held-out and gold items never
enter the corpus or a prompt; the app scores with AI off.

```
just eval-public      # public, offline, no key: metrics + baselines + leakage firewall
```

Real run (this commit): the leakage firewall is intact and the card AI beats the
keyword and TF-IDF baselines; exit 0.

- Full AI tests and the private gate transcript: `docs_pgrep/proofs/feat-proofs.md`.
- AI off proof: `test_pgrep_problem_gen.py::test_ai_off_session_imports_no_heavy_deps`.

[HONEST] The AI beats every baseline but does not clear all absolute cutoffs
(card fact-precision ~0.90 vs 0.95, problem key-correctness ~0.69 vs 0.95); see
`README.md` known limitations and `docs_pgrep/ai/ai-layer.md` section 7.

## 5. Re-runnable tests others can re-run (12%)

The private gate lives in the gitignored `content/` tree, so the public,
self-contained reproduction is the key artifact for a grader.

```
just eval-public      # runs on a committed synthetic sample, deterministic, offline
just check            # full build, lint, and rust/python/typescript tests, green
```

[PROVEN] `just check` is green on this commit. `just eval-public` reproduces the
gold-set-gate methodology (metrics with bootstrap CIs, keyword and TF-IDF
baselines, the beat-baseline rule, the leakage firewall) with no private data.

## 6. Two apps, one engine, with sync (10%)

The iOS app runs Anki's Rust engine through the C FFI and syncs to a self-hosted
server. The scheduler and scores are the shared engine, not a rewrite.

```
just ios-sync-proof                                   # phone uploads, desktop downloads
python -m pytest pylib/tests/test_pgrep_sync_roundtrip.py
```

iOS build and the on-device attempt-write test pass (`xcodebuild ... build` and
`... test` both succeed). Conflict rule: `docs_pgrep/contracts/L3-sync-conflict-rule.md`.

[RECORD] Review a card or run an exam on the phone, Sync, then Sync on the
desktop and show it appear. This is the headline shared-engine + sync shot.

## 7. Useful product and clean UX (8%)

Desktop surfaces: Home, Study (cards, problems ladder, timed exam), Progress,
Settings, Library. iOS: Home, Study, Progress, Settings, with cards, the
wrong-answer ladder, a timed exam, native Memory/Performance/Readiness, and math
rendering.

[RECORD] A short walkthrough of both apps.

## Speed and reliability (spec section 10 and 7h)

```
just bench --cards 50000
```

Real run at 50000 cards: next-card p95 0.16 ms (target < 100 ms), dashboard
first-load p95 446 ms (target < 1 s), refresh p95 421 ms (target < 500 ms).
[PROVEN] 3 of 3 measurable targets pass.

## Crash and offline (spec section 7g)

```
just crash-test
```

Real run: 20 mid-review SIGKILLs, 20/20 reopened clean, SQLite integrity plus
Anki fsck OK, 0 lost committed reviews. [PROVEN]

## Installers and clean-device runs (Sunday)

The desktop app is pgrep-branded (name, bundle id, icon). Build, sign, notarize,
and iOS distribution steps: `docs_pgrep/reference/installer-and-distribution.md`.

- Desktop: build the installer, install the package on a clean machine, launch
  pgrep, run a review. [RECORD]
- iOS: sideload or TestFlight, install on a device or a fresh Simulator, run a
  review. [RECORD]
- Both run with AI off: `just run` (desktop) and the iOS default. [PROVEN]

## Hard-limit status (spec section 11)

- Real Rust change: yes, PointsAtStake with 11 Rust + 2 Python tests. Clears the
  50% cap.
- Phone shares the engine and syncs: yes, FFI + two-way sync. Clears the 70% cap.
- Re-runnable test setup: `just eval-public` and `just check` from the public repo.
- Held-out testing: memory calibration and the held-out eval pipeline.
- Made-up readiness: no, the app abstains without data. No auto-fail.
- Runs on a clean device: build path and docs ready; the clean-device clips are
  yours to record.
- Leaked test data: the leakage firewall is clean.
- AI with no traceable source: no, every output cites or refuses.
