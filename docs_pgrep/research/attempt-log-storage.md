# Attempt / Event Log Storage

**Status: LOCKED — "A now, C-ready."** Ship **A (notes-as-log)** as the synced source of truth; engineer it so **C (a local recomputable cache)** can be added later at zero sync/undo cost. **B rejected** (jeopardizes the graded sync requirement). Feeds `technical-architecture.md` (d) data model. This is the store for the **append-only problem-attempt / event log** that powers the Performance model + calibration.

## Scope clarification (narrows the problem)

There are **two logging channels**, and only one is in question:

- **Card (memory) reviews → Anki's `revlog`** — already exists, already syncs free (union by id), already captures correctness (via rating) + latency. **No decision needed.**
- **Problem (performance) attempts → the "attempt log"** — richer than revlog can hold: selected option, ladder depth, sub-goal productions, session id, device/HLC. **This doc is only about where *this* lives.**

That also bounds the volume: the attempt log grows with **problem attempts** (relatively few), not with every flashcard review.

## What the log must do (requirements)

| # | Requirement |
|---|---|
| R1 | **Append-only** — write-once forensic record, never mutated |
| R2 | **Two-way incremental sync** across devices, no loss/dup, clean merge (the spec's core requirement) |
| R3 | **Feeds analytics** — the Performance + calibration fold (group by topic, recent window, correctness/latency) |
| R4 | **Undo-safe + crash-safe** (spec 7g: zero corruption) |
| R5 | **Scales** without polluting study/stats |
| R6 | **Low build cost** / one-week timeline / "reuse Anki (brownfield)" |
| R7 | **Resilient to Anki schema upgrades** |

## The options

- **A — Notes-as-log:** a suspended "Attempt" notetype, one note per event; cards parked in a hidden deck.
- **B — Custom SQLite table:** a dedicated `attempts` table in the collection DB, typed/indexed rows.
- **C — Hybrid:** notes are the **synced source of truth** (A), plus a **local, recomputable materialized table** rebuilt from the notes for fast analytics (not synced).

## Comparison

| Req | A · Notes-as-log | B · Custom table | C · Hybrid |
|---|---|---|---|
| R1 append-only | ✅ write-once notes | ✅ | ✅ |
| **R2 sync** | ✅✅ **free** — chunked, USN-merged, unions by id | ❌ Anki's incremental sync ignores unknown tables → **must write custom sync** (USN/graves/chunk/merge/sanity) or it only rides full-sync / goes device-local | ✅✅ notes sync free; cache is local |
| R3 analytics | ⚠️ fields are strings → parse/search (workable, slower) | ✅✅ typed columns, indexed `GROUP BY` | ✅✅ rebuild indexed cache from notes |
| R4 undo/crash | ✅ Anki note undo + WAL on core tables | ⚠️ custom undo (remove last row) + must ride WAL | ✅ notes undo; cache is rebuildable |
| R5 scale/pollution | ⚠️ each note spawns a card to suspend + hide from study/stats | ✅ small rows, no card pollution | ⚠️ same card pollution as A |
| R6 build cost | ✅ notetype + Python; **no sync code** | ❌ migration + custom sync (heavy Rust) | ⚠️ A + a local fold (no sync code) |
| R7 upgrade-resilient | ✅ notes are core | ⚠️ Anki schema migrations/sanity may not expect an extra table | ✅ |

## The crux: sync (R2)

This is the whole ballgame, because sync is the spec's central, heavily-graded requirement.

- **A/C ride Anki's note sync unchanged** — the append-only log gets two-way incremental sync, USN conflict handling, and id-union dedup *for free*, and it's automatically consistent with the conflict rule we already documented (revlog + notes both union by id).
- **B breaks on the common path.** Anki's *normal* (incremental) sync only moves known tables. A custom table would: (i) need a full custom sync implementation inside `rslib/src/sync/**` (USN tracking, graves, chunking, merge, sanity) — significant, risky Rust; or (ii) ride only *full* sync (whole-file upload/download), which does **not** happen on normal syncs → the table **diverges across devices after any normal sync**; or (iii) stay device-local → violates the two-way requirement outright.

## Upsides / downsides, distilled

**A — Notes-as-log.** ➕ free sync, minimal code, upgrade-safe, conflict-consistent. ➖ string-field analytics, and each log note spawns a card you must suspend + hide (mitigable, and the cohort does exactly this).

**B — Custom table.** ➕ clean typed schema, fastest analytics, no card pollution. ➖ **loses the sync requirement unless you write custom sync**; higher build cost; upgrade risk. Only sane if we accept device-local analytics or invest heavily in sync Rust.

**C — Hybrid.** ➕ A's free sync **and** B's fast analytics (rebuild the indexed cache from the notes on demand); cache is recomputable so it carries no sync/undo risk. ➖ still has A's suspended-card overhead; a bit more code than pure A (the fold/materialization).

## Locked decision — **"A now, C-ready"**

- [x] **A · notes-as-log** — ship now (the synced source of truth).
- [ ] **B · custom table** — **rejected**: jeopardizes R2, the spec's most heavily-graded requirement (would force risky custom sync in `rslib/src/sync/**`).
- [x] **C · hybrid** — **deferred but pre-engineered**: add the local recomputable cache only if/when the fold gets slow. A must be built so this evolution is ~free.

**Why:** R2 (two-way sync) dominates. A rides Anki's note sync for free and ships fastest; C is a *pure local optimization* we can bolt on later with no sync/undo cost — **provided A is built for it.** Those capacity constraints (K1–K5) are the deliverable of this decision.

### What "A now, C-ready" requires (build into A from day one)

| # | Constraint | Why it makes C ~free later |
|---|---|---|
| K1 | **Attempt note = immutable, self-contained event.** Never edited after write; carries everything the fold needs (no external joins). | The cache is a **pure function of the notes** → rebuildable anytime, zero sync risk. |
| K2 | **Event identity = the note guid.** Every fold/cache keys on it. | Idempotent rebuild + union-by-id dedup, consistent with the documented sync conflict rule (revlog/notes union by id). |
| K3 | **Payload = one JSON blob field** (`event_json`) **+ a few denormalized flat fields** for the hottest filters (`topic`, `correct`, `answered_at`); topic also on **tags** for cheap tag-search pre-filter. | A parses JSON on demand; C parses the **same** JSON into typed cache rows — no schema redesign, just a materialization pass. |
| K4 | **One read-model seam.** All attempt analytics go through a single interface — `attempts(topic, window) → [Event]` + `performance_fold(…)`. Callers (Performance L5, calibration dashboard) never touch storage directly. | Flipping A→C = swap the impl behind the seam; **zero caller changes, zero sync changes.** |
| K5 | **Define the cache now, build later.** `cache = fold(all Attempt notes)`, **local-only, never synced**, recomputable; rebuilt on cache-miss / version bump / corruption. | The only table we'd ever add is local + recomputable → it **never touches `rslib/src/sync/**`**, so we never drift into B. |

### Flip trigger (when to actually build C)
Stay on pure-A on-demand folding until it measurably hurts: **add the C cache when the dashboard/performance fold over the analytics window exceeds ~150 ms on-device, or attempt volume passes a few thousand events.** Volume is bounded (problem attempts, not every flashcard review), so this may never trigger inside the project window — which is exactly why A is safe to ship first.

_Sources: sync/mobile exploration (agent c406326e); cohort schema work (stephen.zhang `PerformanceEvent`, alan.abraham `Performance Attempt`, linjian.ni custom `attempts` table + "Explore data model sync"); Anki `rslib/src/sync/**`, notes/notetypes/`custom_data`/config constraints. Cohort claims [verify]._
