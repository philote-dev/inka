# Engine prune, design (turning the fork into our own engine)

Date: 2026-07-07. Status: strategy and methodology, gated. Author: pair session.

## Context

The long-term goal is to reduce the repo to only what pgrep uses, owning the
engine outright. This is large, strategic, and distinct from the interface prune,
which is safe and near-term (`structural-de-anki-design.md`). This document
frames the decision, the risk, and a safe methodology. It is not yet an execution
plan.

## The pivotal decision (a gate, not a detail)

The moment the engine is pruned, upstream Anki can no longer be merged. The vision
says reuse and modify the engine precisely so pgrep keeps inheriting FSRS, sync,
and scheduler improvements for free. Owning the engine means owning all of that
maintenance forever.

Decide this consciously before starting. Recommendation: stay upstream-mergeable
until the interface is fully pgrep's and there is a concrete reason to diverge.
This prune should be the last of the four workstreams.

## Two prunes, do not conflate

- Interface prune (separate doc): safe, removes Anki's user-facing UI. Do it
  first.
- Engine prune (this doc): risky, strips `rslib`, `pylib`, and `proto` down to
  pgrep's used surface.

## Methodology (when we execute)

1. Map the architecture and dependencies first, so the audit is tractable rather
   than guesswork. The understand-anything plugin produces a layer and dependency
   graph to prune against.
2. Define pgrep's real entry points: the `mediasrv` handlers, the `anki.pgrep.*`
   modules, the iOS FFI surface, and the sync client.
3. Measure reachability from those, both at runtime (`just coverage` plus the e2e
   suite) and statically (`vulture` for Python, `knip` or `ts-prune` for TS,
   `cargo-machete` and `cargo +nightly udeps` for Rust dependencies).
4. Remove whole subsystems, biggest and safest first (add-ons, importers, the deck
   browser and reviewer once pgrep fully replaces them, the AnkiWeb-account UI),
   running `just check` and `just test-e2e` green after each removal.
5. Keep an explicit load-bearing allowlist so nothing quietly holding the app up
   is cut: FSRS, the scheduler, the collection, the sync protocol, media, search,
   and stats.

## Risks

The engine subsystems are deeply interconnected. Coverage gaps can hide reachable
code, so a green suite is necessary but not sufficient. Losing upstream is
permanent. Sequence this last, after the interface prune, the updater, and the
upstream decision.
