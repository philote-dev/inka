# pgrep - Proofs

Physics GRE prep, forked from Anki. No AI (that is Friday).

**Commit:** `a340fa458` · verify live with `git rev-parse HEAD`

## Real Rust engine change

A new review-card order, "points at stake", added to Anki's Rust scheduler
(`rslib/src/scheduler/queue/builder/points_at_stake.rs`): it reorders due cards
by topic weight times student weakness, inside the engine's gather-then-limit
pass.

Safe-seam invariant: it only reorders the in-memory due set. It never mutates
`due`, `interval`, or `memory_state`, never writes collection data, and never
creates an undo entry, so scheduling, undo, and sync stay intact.

Tests: 3 Rust unit tests + 1 Python test (`pylib/tests/test_pgrep_selector.py`),
all passing via `just test-rust` and `just test-py`. The shared engine carries
this change to the phone build too.

```
$ just test-rust
cargo-nextest ... check:rust_test
Build succeeded in 104.74s.

$ just test-py
check:pytest ... n2: ran 3 tasks
Build succeeded in 24.42s.
```

## Fork proof

A fork of Anki that builds from source: `just clean && just run` compiles the
Rust engine, Python, and web, then opens straight into the pgrep UI (not Anki's
deck browser). Ships as a desktop installer:
`out/installer/dist/anki-26.05-mac-apple.dmg`.

```
$ just clean && just run
Build succeeded in 82.46s.
Starting Anki 26.05...
aqt.mediasrv: Serving on http://127.0.0.1:40000
aqt.mediasrv: GET /pgrep      <- opens straight into pgrep
```

## Score honesty

Three separate scores, each shown honestly or not at all:

- **Memory** - real, from the engine's per-topic FSRS retrievability. Shows a
  point, a likely range, and a how-sure read; abstains when a topic is too thin.
  The one that is going to appear on the application (for memory) is derived from the imported sample set.
- **Performance** - abstains: no model yet (that is Friday).
- **Readiness** - abstains: needs performance data and 70% topic coverage first.

No fabricated numbers: the app refuses to show a score it cannot back with data.
