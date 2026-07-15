# pgrep dev harness

pgrep is a Physics-GRE prep app forked from Anki. It reuses Anki's shared Rust
engine across two front-ends:

- **Desktop** — the existing Anki Python/Qt + TypeScript app (`pylib/`, `qt/`,
  `ts/`) on top of the core engine (`rslib/`).
- **iOS (Simulator)** — a native SwiftUI app (`mobile/ios/`) that drives the
  _same_ engine through a small C ABI (`rslib/ffi`), packaged for iOS as an
  `.xcframework`.

This page documents how to build, run, and test both targets with the `just`
recipes in the repo-root `justfile`. Run `just --list` to see everything.

## Desktop

| Command          | What it does                                                                    |
| ---------------- | ------------------------------------------------------------------------------- |
| `just build`     | Build the desktop app (pylib + qt).                                             |
| `just run`       | Build and launch Anki in development mode.                                      |
| `just test-rust` | Run the Rust test suite.                                                        |
| `just test-py`   | Run the Python tests (pylib + qt), including the content-bundle invariant gate. |
| `just check`     | Format + full build + all lint/tests (run before finishing a task).             |
| `just smoke`     | Fast desktop sanity check (see below).                                          |

> **pgrep takeover (L2.5):** `just run` opens directly into the pgrep surface
> (Home / Study / Progress / Diagnostic), not Anki's deck browser. Anki's own
> screens stay reachable via **Tools → Open Anki screens**. The surface mode
> lives in local profile meta (`pgrep_surface_mode`, default `hosted`; set it to
> `off` for stock Anki). See `docs_pgrep/reference/api-contract.md`.

### `just smoke`

`smoke` is a quick, reliable pre-flight check — much faster than `just check`:

1. **Import smoke** — `SKIP_RUN=1 ./run` builds pylib + qt and imports `aqt`
   without opening the GUI, proving the libraries are importable (the same check
   CI runs under the name "Ensure libs importable").
2. **Rust tests** — `just test-rust`.

It deliberately skips the slow Playwright e2e suite. Use `just test-py` /
`just test-ts` / `just check` when you need broader coverage.

## iOS (Simulator)

The iOS app links `out/ios/AnkiFfi.xcframework`, a build artifact produced from
the `rslib/ffi` crate. The Xcode project is generated from
`mobile/ios/project.yml` by [XcodeGen] and is **gitignored** — `project.yml` is
the source of truth, so regenerate the `.xcodeproj` after cloning or whenever
the spec changes. On first launch the app loads the bundled sample deck at
`mobile/sample-deck/collection.anki2`.

### Prerequisites (one-time)

```
# Rust cross-compile targets (Simulator is required; device is best-effort)
rustup target add aarch64-apple-ios-sim aarch64-apple-ios

# Project generator + Swift protobuf codegen (protoc-gen-swift)
brew install xcodegen swift-protobuf
```

You also need Xcode and its command line tools (`xcodebuild`, `xcrun simctl`),
plus at least one iOS Simulator (any recent iPhone).

### Build & test

| Command                | What it does                                                          |
| ---------------------- | --------------------------------------------------------------------- |
| `just ios-xcframework` | Build `out/ios/AnkiFfi.xcframework` via `tools/build-xcframework.sh`. |
| `just ios-smoke`       | End-to-end iOS smoke (headless XCTest; see below). macOS-only.        |
| `just ios-run`         | Build + launch the app **visibly** in the Simulator (see below).      |

`just ios-smoke` delegates to `tools/ios-smoke.sh`, which:

1. builds the xcframework (`tools/build-xcframework.sh`),
2. regenerates the Xcode project (`xcodegen generate` in `mobile/ios/`),
3. auto-detects an available iOS Simulator (the first "iPhone" reported by
   `xcrun simctl list devices available`), and
4. runs the on-Simulator engine XCTest:
   `xcodebuild -project mobile/ios/PgrepStudy.xcodeproj -scheme PgrepStudy
   -destination "platform=iOS Simulator,name=<detected>" test`.

The XCTest (a host-less logic-test bundle) compiles the engine bridge and
generated protos and links the shared xcframework, so a green run proves the
same engine that powers desktop works on iOS.

To target a specific simulator, override the auto-detection:

```
IOS_SIM_NAME="iPhone 16 Pro" just ios-smoke
```

If `xcpretty` is installed it is used to prettify the `xcodebuild` output;
otherwise the raw log is shown. Either way the real test exit status is
preserved.

### Watch it run (visible app)

`just ios-smoke` proves the engine links, but runs _headless_. To actually see
the app on screen, use `just ios-run` (delegates to `tools/ios-run.sh`), which
builds the xcframework + project, then **builds the `PgrepStudy` app target**,
boots a Simulator, opens Simulator.app, and installs + launches
`net.ankiweb.pgrep.PgrepStudy`. You should see the PGRE review loop (Show
Answer -> Answer: Good) with the live Rust-seam footer, all driven by the shared
engine. Target a specific device with `IOS_SIM_NAME="iPhone 16 Pro" just
ios-run`.

Record the running app (for the demo reel) once it is booted:

```
xcrun simctl io booted recordVideo pgrep-ios.mp4
```

Press Ctrl-C to stop recording; the `.mp4` is written to the current directory.

### Opening the app in Xcode

```
cd mobile/ios
xcodegen generate
open PgrepStudy.xcodeproj
```

Pick an iPhone simulator and Run. From the command line you can also boot a
simulator and inspect it with `xcrun simctl` (e.g.
`xcrun simctl list devices available`, `xcrun simctl boot "iPhone 17 Pro"`,
`open -a Simulator`).

### Regenerating Swift protobuf types

The Swift message types under `mobile/ios/PgrepStudy/Generated` are checked in.
Re-run `tools/gen-swift-protos.sh` after changing any `proto/anki/*.proto`.

## Sync server (self-hosted)

pgrep syncs desktop and iOS through a self-hosted copy of Anki's own sync server
(`rslib/src/sync/**`, unmodified). There is no AnkiWeb dependency and no custom
sync code. The conflict rule it enforces is documented in
[`sync-conflict-rule.md`](sync-conflict-rule.md).

| Command                             | What it does                                                         |
| ----------------------------------- | -------------------------------------------------------------------- |
| `just sync-server`                  | Build pylib, then run the server on `0.0.0.0:8090` as `pgrep:pgrep`. |
| `just sync-server user="me:secret"` | Same, with a custom account.                                         |

The sync server uses port `8090`, not `8080`, because `just run` already binds
`8080` for the Qt remote-debug and hot-reload server (`tools/reload_webviews.py`).
The desktop and iOS clients default to `8090` to match, so no address needs
typing.

The recipe runs `tools/sync-server.py`, which mirrors `tools/run.py`'s path
setup and calls `anki.syncserver.run_sync_server()` (the same `SimpleServer` the
packaged `anki --syncserver` uses). macOS/Linux.

Environment (read by the server):

- `SYNC_USER1=user:pass` is set from the recipe's `user` arg. Add more accounts
  with `SYNC_USER2=...` in the environment.
- `SYNC_HOST` (default `0.0.0.0`), `SYNC_PORT` (the `just sync-server` recipe sets
  `8090`), and `SYNC_BASE` (default `~/.syncserver`, one folder per user).

The clients need no address typed (both default to `8090`), but for reference:

- **Desktop:** the pgrep **Settings** Sync section (or Preferences) already points
  at `http://127.0.0.1:8090/`. Log in with the `SYNC_USER1` credentials, then Sync.
- **iOS:** the Settings tab in the app, also defaulted to `8090`.

The iOS Simulator shares the Mac's network, so `http://127.0.0.1:8090/` works
from the Simulator. A physical device needs the Mac's LAN IP. Health check:
`curl http://127.0.0.1:8090/health` returns `200`.

## Demo profile and the sync walkthrough

The three scores abstain honestly until an account has earned them, which is the
correct behavior but leaves a fresh demo account showing "not enough yet"
everywhere. The demo profile injector fixes that on demand. It writes a clearly
marked, hypothetical study history (reviewed cards with FSRS state, plus clean
Attempt notes across most of the blueprint) so Memory, Performance, and
Readiness all produce real numbers. It is a dev tool, reachable only from
`pgrep-lab`, so real user accounts never auto-inject and still abstain by
construction.

What it does and does not light up. It lights up the three **scores** (Memory,
Performance, Readiness). It does not change the **calibration** reliability
diagrams on Progress, which come from embedded offline evaluations rather than
user data. That is expected.

The module is `pylib/anki/pgrep/demo_profile.py`
(`inject_demo_profile`, `clear_demo_profile`, `demo_status`, and
`preview_demo_profile`, which projects a stage's scores without committing),
driven by the dev-only bridge handler `pgrep_demo_profile` in `qt/aqt/pgrep.py`.
Every reviewed card carries the `pgrep::demo` tag and every attempt carries a
`demo` payload flag, so injection is idempotent and `Clear demo` removes exactly
the demo data. There are three stages, a day-one to exam-ready progression:
`diagnostic`, `training`, and `nearing_exam` (the default).

### Inject on the desktop

The dev lab (`/pgrep-lab`, opened from **Tools -> pgrep: open dev lab** in an
`ANKIDEV` build) uses a single top switcher so it reads clearly on camera:
**Home**, **Design** (the manifold, gallery, home layouts, flashcard face, and
math sandboxes, which show how the look and behavior were chosen), and **Demo**
(the injector at `/pgrep-lab/demo`). It is a dev surface with no link from the
shipped Home / Study / Progress flow, so reach it one of two ways.

- Inside the running app (no flags). Run `just run`. The `just run` log prints a
  remote debugging URL (for example `http://127.0.0.1:8080`, the Qt debug port,
  distinct from the sync port `8090`). Open it in Chrome,
  pick the pgrep page, and run `location.assign('/pgrep-lab/demo')` in the
  console. The page loads inside the app's webview, which injects the bridge
  auth header, so its buttons work.
- In a plain browser (dev convenience). Launch with the local API open,
  `ANKI_API_HOST=0.0.0.0 just run`, then open
  `http://127.0.0.1:40000/pgrep-lab/demo` in any browser. This flag lets a
  non-webview page reach the bridge, so use it only on a trusted dev machine.

Then the click path is the same:

1. Pick a stage (**Diagnostic**, **Training**, or **Nearing exam**). The three
   score cards preview that stage immediately, with a dashed accent to mark them
   as a projection. Then click **Inject** to commit it: the accent goes solid and
   the coverage bar clears the 70% Readiness gate. Every stage clears every gate;
   the later stages just project higher scores.
2. Open the real **Progress** surface to confirm Memory, Performance, and
   Readiness now render live scores with ranges. **Clear demo** on the lab page
   removes it again.

### Push it desktop to mobile

The clients need no setup: the desktop Settings surface and the iOS app both
default to `http://127.0.0.1:8090/` and the account `pgrep`, so syncing is a
one-click, no-address-to-type experience once the server is up. The only reason
that address exists at all is that pgrep self-hosts the sync server (constraint
2) instead of AnkiWeb; baking the default in makes it behave like a normal
account sign-in.

**One-command path (recommended).** Prime the whole account off-camera, then
just sync down on each device:

1. Start the server: `just sync-server` (serves `pgrep:pgrep` on `0.0.0.0:8090`).
2. `just pgrep-demo-sync`. This seeds the real cards and problems, injects the
   made-up stats and a couple of settings, uploads it as `pgrep`, then verifies a
   second engine downloads it and recomputes the same scores. Pass a stage with
   `PGREP_DEMO_PROFILE=diagnostic just pgrep-demo-sync`.
3. Desktop: pgrep **Settings** -> **Sync** (server and account are pre-filled).
4. iOS: `just ios-run`, then **Settings** -> **Sync** (also pre-filled). The
   Simulator shares the Mac network, so `127.0.0.1:8090` works.

Both ends now show the same lit-up Memory, Performance, and Readiness, computed
on the shared engine from the synced account.

**In-app path (shows the injection live).** If you want the injection on camera:

1. Start the server: `just sync-server`.
2. On the desktop, open **Demo** (`/pgrep-lab/demo` from the lab hub),
   pick a stage (its scores preview), **Inject**, then **Sync now** right there on
   the page (it reuses the same sign-in as Settings). The three score cards switch from
   "Abstains" to real numbers first.
3. On iOS: `just ios-run`, open **Settings**, and Sync. Record it with
   `xcrun simctl io booted recordVideo pgrep-ios.mp4`.

To reset, click **Clear demo** on the desktop lab page and sync both ends again,
or sync a fresh account.

## Live AI (optional)

The app scores and studies with AI off, and AI stays off by default. To demo the
live upgrades (the tutor grading a typed sub-goal on the wrong-answer ladder, and
Library generation), turn it on:

1. Install the optional AI runtime once: `just pgrep-ai-deps` (adds `openai`,
   `sympy`, `fastembed`, `sqlite-vec`, and `numpy` to `out/pyenv`, outside the
   default build).
2. Launch with the key in the environment: `just run-ai` loads `OPENAI_API_KEY`
   from your shell or from `content/.env`, then runs. It also pins a known-good
   dated chat snapshot in `PGREP_AI_MODEL` (default `gpt-5.5-2026-04-23`, override
   as needed), because the auto-picker can otherwise land on a non-chat `gpt-5`
   model on some accounts. The chosen model is cached in the collection config on
   first use.
3. In **Settings**, toggle **AI** on. The status turns ready only when the key is
   present, so the toggle never claims AI is on when it cannot run.

With AI on, a miss on a Problem opens the ladder and the "break it down" rung
grades the learner's typed sub-goal live, with the giveaway verifier guarding the
final answer. The tutor path needs only `openai` and the key; live Library
generation additionally needs the private corpus index in `content/`.

## Content pipeline

The shipped content bundle (`content_bundle.json`, the cards and problems) has its
own build, gate, and audit tools. Full detail, including the deep modules they
share (one LLM client, one Judge), is in
[`content-pipeline.md`](content-pipeline.md).

| Command                                   | What it does                                                                               |
| ----------------------------------------- | ------------------------------------------------------------------------------------------ |
| `python content/tools/assemble_bundle.py` | The single landing command: land, convert math, wire figures, then run the invariant gate. |
| `just test-py`                            | Runs the Python tests, including the deterministic bundle invariant gate (per-commit).     |
| `just audit-bundle-ai`                    | Runs the five on-demand AI content audits (pre-release or nightly).                        |
| `just check`                              | The overall gate; it includes `test-py`, so it also runs the bundle invariants.            |

The invariant gate is deterministic and needs no key. The AI audits need the
optional AI runtime (`just pgrep-ai-deps`) and `OPENAI_API_KEY`; the three HARD
audits (answer_key, figure_fidelity, decomposition_leak) fail the run on findings,
the two SOFT ones (distractor_plausibility, citation) report only.

## CI (follow-up)

A macOS GitHub Actions job could run `just ios-smoke` on every PR to guard the
iOS build + engine link (the desktop side is already covered by existing CI).
This is **not added yet** — it's pending an owner decision (macOS runner cost /
minutes), so no `.github/workflows/` changes have been made.

[XcodeGen]: https://github.com/yonaskolb/XcodeGen
