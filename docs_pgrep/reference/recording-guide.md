# pgrep recording guide

What you need to capture for the submission, and the exact steps. There are two
deliverables: a 3 to 5 minute demo video, and clean-device install-and-run clips
for both apps. Everything below runs locally.

## 0. One-time setup (already running for you)

I have these up already, so you can start recording the desktop immediately:

- Desktop app with AI available: `just run-ai` (serving at http://127.0.0.1:40000).
- Self-hosted sync server: `just sync-server` on port 8090 (account `pgrep` / `pgrep`).

If you need to restart them later:

```
just sync-server            # terminal 1, leave running (port 8090)
just run-ai                 # terminal 2, desktop app with AI (needs OPENAI_API_KEY in content/.env)
```

Light up the three scores before recording (a fresh account honestly shows
"not enough yet", which is correct but not what you want on camera):

1. In the app, open the dev lab at http://127.0.0.1:40000/pgrep-lab.
2. Go to Demo control, pick "Strong learner", click Inject profile.
3. Home now shows Memory, Performance, and Readiness with real numbers and ranges.

Turn AI on in Settings (it is off by default) so you can demo generation.

## 1. Demo video shot list (3 to 5 minutes)

Record these in order. Each maps to a spec grading area.

1. Review session (desktop): Home, then Start session, answer a few cards
   (Show answer, then Good / Again). This is the shared-engine FSRS loop.
2. The Rust engine change: in a terminal run `just test-rust` and show the
   points-at-stake tests pass, then open
   `rslib/src/scheduler/queue/builder/points_at_stake.rs` and say one line about
   what it does (orders due cards by blueprint weight times topic weakness, in
   memory only, never mutating scheduler state). Optionally show
   `pylib/tests/test_pgrep_selector.py` proving it from Python.
3. The three scores with ranges: Home cards (each shows a point value, an 80%
   range, a how-sure line, and coverage), then open the Progress tab for the
   coverage bar and the calibration reliability diagrams.
4. Exam mode: Study, then Exam, run a timed multiple-choice mock, finish, and
   show the projected scaled score with its range.
5. Wrong-answer ladder: Study, then Problems, commit an answer first, walk the
   hint rungs, then reveal. This is the productive-failure feature.
6. AI features with sources: Library, author a seed, generate, and show the
   result cites a named source. Show it refusing when a claim is unsupported.
7. Phone to desktop sync: on the iOS app review a card (or run an exam), Sync,
   then on the desktop Sync and show the review or attempt appear. This is the
   two-apps-one-engine proof.
8. Honesty shot (optional but strong): show an abstaining state ("not enough of
   the exam is covered yet") to prove the app refuses a score without data.

## 2. Test and evaluation evidence (screen-record the terminal)

These are the "prove it" clips. Each prints a clear pass or an honest result.

```
just eval-public            # eval methodology + leakage firewall, exit 0
just bench --cards 50000    # p50/p95/worst latency, targets pass
just crash-test             # 20 mid-review kills, 0 corruption, 0 lost reviews
just check                  # full lint + rust/python/typescript tests, green
```

The AI gate and the study-feature ablation are reported honestly in the README
"known limitations": the AI beats the keyword and vector baselines but does not
clear every absolute cutoff, and the interleaving selector beats a blocked
variant but loses to plain Anki at 10 reviews per day. Showing an honest
negative scores well, so it is worth a sentence on camera.

## 3. iOS app (record in the Simulator)

Once the app is launched (I will start `just ios-run` for you):

1. Settings tab: set the sync URL to `http://127.0.0.1:8090/`, log in with
   `pgrep` / `pgrep`, Sync.
2. Study tab: review a few cards.
3. Home tab: show Memory, Performance, and Readiness (they light up once the
   synced attempts arrive from desktop), and the Progress screen.
4. Run a timed exam.

Record the Simulator to a file:

```
xcrun simctl io booted recordVideo pgrep-ios.mov      # Ctrl-C to stop
```

## 4. Clean-device install clips

Full build, sign, notarize, and iOS distribution steps are in
`docs_pgrep/reference/installer-and-distribution.md`. Short version:

- Desktop: build the installer, then on a clean machine install the produced
  package and launch pgrep, record the first run and a review.
- iOS: sideload the build or use TestFlight, install on a device or a fresh
  Simulator, and record a review.

## 5. Both apps run with AI off

Show `just run` (desktop, no AI) still producing scores, and note the iOS app
has AI off by default. This satisfies the "runs with AI switched off" rule.
