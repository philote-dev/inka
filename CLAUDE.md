# Claude Code Configuration

> **Note:** Every command you need — building, running, testing, linting,
> formatting — is defined as a recipe in the project `justfile`. Run
> `just --list` to see them. Do not invoke `./ninja`, `./run`, or scripts
> under `./tools` directly — use the `just` recipes instead.
>
> `AGENTS.md` is a symlink to this file, so both point at the same guidance.

## Project Overview

This repo (**inka**) is **pgrep** ("Physics GRE Speedrun") — a focused Physics
GRE (PGRE) prep app built by **forking [Anki](https://apps.ankiweb.net)**. It
ships a desktop app and an iOS companion on **one shared Rust study engine**,
and reports three separate, honest numbers: what you can **recall** now
(Memory), **apply** to a new problem (Performance), and **would score** today
(Readiness). Desktop AI defaults **on** on first run (Settings can turn it
off); the iOS companion stays AI off. Both apps still build, study, and score
with AI switched off.

Think of the codebase as **two layers**:

1. **The Anki base** — the unmodified (or lightly patched) upstream Anki
   architecture. Almost all build tooling, the sync engine, FSRS scheduling,
   the collection/data model, protobuf IPC, and translations come from here and
   still work as upstream documents them.
2. **The pgrep product layer** — everything added on top for the PGRE product.
   It lives in clearly-named `pgrep` modules/dirs across every language layer
   (see "Where pgrep code lives"). When in doubt, a file or directory with
   `pgrep` in its name is ours; the rest is inherited Anki.

### Anki's multi-layered architecture (inherited)

- Web frontend: Svelte/TypeScript in `ts/`
- PyQt GUI, which embeds the web components, in `qt/aqt/`
- Python library which wraps the Rust layer in `pylib/` (Rust module in `pylib/rsbridge`)
- Core Rust layer in `rslib/`
- Protobuf definitions in `proto/` that the layers use to talk to each other

## Where pgrep code lives

The product layer is intentionally named so it is easy to find and easy to keep
separate from inherited Anki:

- **Engine (Rust):** `rslib/src/scheduler/queue/builder/points_at_stake.rs` is
  the graded engine change — the pgrep "points at stake" review selector. Other
  pgrep touch-points are marked in `rslib/src/collection/service.rs`,
  `rslib/src/scheduler/queue/builder/`, and `rslib/src/storage/card/`.
  `rslib/ffi/` is the C FFI (`lib.rs`, `include/anki_ffi.h`) the iOS app links.
- **Core logic (Python):** `pylib/anki/pgrep/` holds the pure-Python product
  logic — the three scores (`memory.py`, `performance.py`, `readiness.py`,
  `readiness_constants.py`), `exam.py`, `calibration.py`, `coverage.py`,
  `diagnostic.py`, `study.py`, `card_sets.py`, `attempt_log.py`, `tutor.py`,
  `problem.py`/`problem_gen.py`, `generation.py`, `manifold.py`, `settings.py`,
  the shipped `content_bundle.json`, and the bundle gate
  (`content_invariants.py`). The optional AI layer is under
  `pylib/anki/pgrep/ai/`.
- **Desktop shell (Qt):** `qt/aqt/pgrep.py` (the JSON bridge, "Channel B"),
  `qt/aqt/pgrep_window.py`, `qt/aqt/pgrep_host.py`, `qt/aqt/pgrep_about.py`.
- **Web surfaces (Svelte/TS):** `ts/routes/pgrep/` (the shipped product
  surfaces: study, progress, settings, library, diagnostic, exam),
  `ts/routes/pgrep-lab/` (the dev-only lab: calibration, card-sets, demo,
  gallery, manifold, tutor), and shared code in `ts/lib/pgrep/`. Design tokens
  live in `ts/lib/sass/_pgrep.scss`.
- **iOS companion:** `mobile/ios/` (the `PgrepStudy` XcodeGen project) and
  `mobile/sample-deck/`.
- **Content pipeline (Python tools):** `content/tools/` (~70 tracked scripts;
  the private data they read/write is git-ignored).
- **Docs:** `docs_pgrep/` (design, research, plan, contracts, AI methodology,
  proofs). `design/` holds the UX/brand material.

## Running

Every build/run/test/lint step is a `just` recipe (`just --list` for the full
set). Develop is browser-first; both apps still build and score with AI off.

```bash
# Develop (headless serve, no window; AI on by default)
just dev              # :40000, live-reload; just dev --ai off to disable AI
just dev-window       # product window onto the running dev serve
just serve-tail       # phone preview via Tailscale (same serve)
just serve-sync       # self-hosted sync server, port 8090

# Preview the product as users get it (dev mode off)
just preview          # exclusive surface, your profile
just preview-fresh    # throwaway first-time-user profile
just preview-optimized

# One-time AI deps (per checkout / worktree)
just ai-deps

# iOS companion (macOS only)
just ios-run
```

`just dev` serves http://127.0.0.1:40000 (`/pgrep`, `/pgrep-lab`). Edits
live-reload in the browser and on phone. Multi-branch: `just review` (headless
instances on offset ports); `just review-sync` keeps a combined review branch
fresh.

## Building/checking

`just check` formats the code and runs the main build & checks. **Do this as a
final step before marking a task completed.** `just verify` runs `check` plus
the Playwright e2e suite — the pre-ship gate.

Run `just` (or `just --list`) to see all available commands.

## Quick iteration

During development, build/check subsections of the code:

- Rust: `cargo check`
- Python: `just lint` (mypy/ruff), and if wheel-related, `just wheels`
- TypeScript/Svelte: `just lint` (includes check:svelte and check:typescript)

Language-specific tests: `just test-rust`, `just test-py`, `just test-ts`. Use
`just fmt` / `just fix-fmt` for formatting and `just fix-lint` to auto-fix lint.
`just smoke` is a fast desktop sanity check (import smoke + Rust tests).

The pgrep Python tests are extensive — `pylib/tests/test_pgrep_*.py` cover the
three scores, calibration, coverage, the selector, the AI seam/judge, sync
round-trip, and content invariants; `qt/tests/test_pgrep_bridge.py` covers the
JSON bridge. Add a matching `test_pgrep_*` test when you touch product logic.

Browser e2e tests live in `ts/tests/e2e/` and run with `just test-e2e`; the
harness launches a temporary instance and drives mediasrv pages with
Playwright's Chromium.

Be mindful that some changes (such as modifications to `.proto` files) may need
a full build with `just check` first.

## pgrep architecture

- **The three scores** are the product's reason to exist — the memory →
  performance → readiness bridge stock Anki lacks. Memory = P(recall now) via
  FSRS; Performance = P(correct on a _new_ exam-style question); Readiness =
  projected 200–990 score with an explicit range, coverage gate, and abstain
  ("not enough yet") rule. The math and the honest negatives are documented in
  `docs_pgrep/research/three-scores.md` and `performance-model.md`. The exam
  model (100 five-choice MCQ / 170 min, formula-scored, official raw-to-scaled
  table shipped as numeric constants) is in `pylib/anki/pgrep/exam.py` and
  `readiness_constants.py`.
- **The JSON bridge (Channel B):** `qt/aqt/pgrep.py` registers plain `mediasrv`
  POST handlers. `mediasrv` camelCases the handler name, so `pgrep_memory_score`
  is reachable at `POST /_anki/pgrepMemoryScore`. Each handler lazily imports
  the relevant `anki.pgrep.*` module, calls a pure-Python function on
  `aqt.mw.col`, and returns JSON bytes. Keep product logic in `anki.pgrep.*`
  (pure, testable) and let the bridge stay a thin adapter. The contract is
  `docs_pgrep/contracts/L2-api-contract.md`.
- **The engine change** is real (a spec requirement): the "points at stake"
  review selector in `points_at_stake.rs` reorders the review queue by how many
  exam points a card is worth, not just by due date.

## AI layer & content pipeline (optional; desktop on by default, always skippable)

AI only adds card/problem generation and the decomposition tutor; every AI
output must cite a **named source** or refuse, and is checked against a gold set
and a baseline. The layer is imported lazily so an AI-off app never loads
`openai`.

- **One LLM seam:** `pylib/anki/pgrep/ai/llm.py` `LLMClient` is the single seam
  for every model call — it pins an exact dated model snapshot (refuses a
  floating alias), and `load_api_key(...)` is the one place that resolves
  `OPENAI_API_KEY` (env → `content/.env` → repo-root `.env`).
- **One Judge:** `pylib/anki/pgrep/ai/judge.py` `Judge` is one independent judge
  over an injectable client (a fake in tests, so the module never touches the
  network). It grades with a snapshot distinct from the generator so a model
  never grades its own output.
- **The bundle gate (per-commit):** `pylib/anki/pgrep/content_invariants.py`
  holds deterministic invariants over the shipped `content_bundle.json` and runs
  as a gate. The on-demand AI audits (answer-key solve, figure fidelity,
  decomposition leak, distractor plausibility, citation) run via
  `just audit-bundle-ai` — a pre-release scan, not a per-commit gate.
- **Content pipeline:** ~70 tracked tools under `content/tools/` turn the open
  corpus into `content_bundle.json`. The private data (corpus, gold/held-out
  sets, RAG index, ETS constants, `content/.env`) is **git-ignored and never
  committed** — the code that operates on it is. Key recipes:
  `just gen-decompositions`, `just eval-public` (offline reproducible eval),
  `just bench`, `just crash-test`. See
  `docs_pgrep/reference/content-pipeline.md` and `docs_pgrep/ai/ai-layer.md`.

Never commit copyrighted or held-out material, API keys, or `content/.env`.

## iOS companion

`mobile/ios/` is an XcodeGen project (`project.yml` is the source of truth; the
generated `.xcodeproj` is git-ignored). It links the shared Rust engine via the
C FFI xcframework (`out/ios/AnkiFfi.xcframework`, a build artifact produced by
`tools/build-xcframework.sh`). It runs real review sessions on the shared engine,
shows the three scores, and syncs two-way with desktop. Recipes (macOS only):
`just ios-xcframework`, `just ios-manifold`, `just ios-mathjax`, `just ios-run`,
`just ios-smoke`, `just ios-sync-proof`. It is a companion being extended toward
desktop parity, not yet a full mirror.

## Translations

`ftl/` contains the Fluent translation files. Scripts in `rslib/i18n`
auto-generate a type-safe API for Rust, TypeScript, and Python. Make changes to
`ftl/core` or `ftl/qt`; except for Qt-specific features, prefer the core module.
When adding new strings, confirm the appropriate ftl file first and match the
existing style.

## Protobuf and IPC

The build scripts use the `.proto` files to define the Rust library's non-Rust
API. `pylib/rsbridge` exposes that API, and `_backend.py` exposes snake_case
methods for each protobuf RPC that call into the API. Similar tooling creates a
`@generated/backend` TypeScript module for talking to the Rust backend (over
POST requests). Note that pgrep's product surfaces talk to Python over the
`mediasrv` JSON bridge ("Channel B", above) rather than protobuf.

## Fixing errors

When dealing with build errors or failing tests, invoke `check` or one of the
quick-iteration commands regularly to verify your changes. To locate other
instances of a problem, run the check again — don't grep the codebase.

## Conventions

- **Rust dependencies:** prefer adding to the root workspace and using
  `dep.workspace = true` in the individual Rust project.
- **Rust utilities:** `rslib/{process,io}` provide file/process helpers with
  better error messages and ergonomics — use them when possible.
- **Rust error handling:** in `rslib`, use `error/mod.rs`'s `AnkiError`/`Result`
  and snafu. In other Rust modules, prefer anyhow + added context. Unwrapping in
  build scripts/tests is fine.
- **Installer:** the Briefcase-based installer is in `qt/installer`, with
  per-platform templates (`mac-template/`, `linux-template/`,
  `windows-template/`). pgrep ships its own identity (icons, metadata).
- **Provenance:** any AI-generated content must trace to a named source or
  refuse. Keep the AI layer optional and lazily imported.

## Docs map

`docs_pgrep/` is the durable reference — start at `docs_pgrep/README.md`. Notable:

- `research/` — the "why" behind each part (three scores, features, the engine
  change, technical architecture).
- `contracts/` — durable technical contracts the code depends on (L1 schema,
  L2 API contract, L3 sync conflict rule).
- `reference/content-pipeline.md`, `reference/dev-harness.md`,
  `reference/content-and-dependencies.md` — operational how-to.
- `ai/` — AI methodology, gold-set spec, cutoffs/baselines, leakage firewall.
- `plan/` — the build plan and phase-tagged design docs.

## Ignores

The files in `out/` are auto-generated; mostly ignore that folder, though
`out/{pylib/anki,qt/_aqt,ts/lib/generated}` can help when dealing with
cross-language / generated code. The private `content/` data tree (everything
under `content/` except tracked `content/tools/`) is git-ignored.
