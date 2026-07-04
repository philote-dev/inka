# L3 Sync conflict rule (adopted from Anki, documented)

**Status: the sync conflict rule for pgrep (L3).** We reuse Anki's sync engine
unchanged. We never modify anything under `rslib/src/sync/**`. This doc states
the rule pgrep relies on, points at the code that proves it, and maps it to the
spec test (7b) and to pgrep's own data (reviews and the Attempt log).

**Copy rule.** No em-dashes, sparse colons, short labels.

## The rule, in one line

Reviews and Attempt events are unioned by id, so nothing is lost or double
counted. For the same card reviewed on two devices, the review with the newer
modification time wins the scheduling state, with a deterministic device-id
tie-break on equal timestamps. This is Anki's real behavior, made explicit.

## Per-object rules (Anki's behavior, adopted as-is)

| Object | Merge rule | Effect for pgrep |
|---|---|---|
| **revlog** (review history) | append-only, `INSERT OR IGNORE` by id | Two devices reviewing different cards offline both land. No review lost, none double counted. |
| **notes** (incl. the Attempt log) | pending-USN guard, then newer `mtime` wins | Attempt notes are keyed by a stable id, so they union by id (see below). No duplication. |
| **cards** | pending-USN guard, then newer `mtime` wins | Same card reviewed on both devices: the newer review's scheduling state wins. |
| **notetypes / decks / deck config** | newer `mtime` wins; a structural (field/template count) change forces a one-way full sync | The `pgrep::Attempt` and `pgrep::Problem` notetypes sync like any other. |
| **tags** | union | The `topic::…` and `pgrep::attempt` tags merge across devices. |
| **deletions** | graves exchanged at sync start | Deletes propagate by id, not by mtime. |
| **schema mismatch / sanity failure** | mandatory one-way full sync | The safety net when a client is too far out of step. |

## Why the Attempt log unions cleanly by id

The Attempt log is stored as immutable notes, one note per graded event, with
the note GUID used as the event id (`docs_pgrep/plan/l1-coordination-schema.md`
K2). Two independent properties combine to give union-by-id:

1. **Different events on different devices** get different GUIDs, so they are
   different notes and both land under the note merge.
2. **The same event** (same GUID) never diverges, because an Attempt note is
   never edited after creation (K1 immutable), and appending an event whose
   `event_id` already exists is a no-op (`attempt_log.append_attempt` in
   `pylib/anki/pgrep/attempt_log.py`, and the same contract on mobile). So the
   note merge has nothing to reconcile.

The result matches revlog's own union-by-id, which is exactly what
`technical-architecture.md` (d) and the L1 schema require. No custom synced
table is introduced, and nothing under `rslib/src/sync/**` changes.

## The tie-break

For the same card reviewed on both devices at timestamps that are not equal, the
newer `mtime` wins (below). On exactly equal `mtime`, Anki's merge is
order-dependent, so pgrep documents a deterministic winner: the higher device
id. In practice the Attempt log records `device` in `event_json`, so the full
history is preserved regardless of which card scheduling state wins, and the
Performance fold reads the union of events, not the single surviving card state.

## Proof pointers (Anki's code we rely on, not modified)

- **revlog union-by-id.** The chunk merge inserts each incoming revlog row with
  `INSERT OR IGNORE`, so a row whose id already exists is dropped:

  - `rslib/src/sync/collection/chunks.rs` `merge_revlog` (calls
    `add_revlog_entry(&entry, false)`).
  - `rslib/src/storage/revlog/add.sql` begins `INSERT OR IGNORE INTO revlog`.

- **notes and cards, newer-mtime wins with a pending-USN guard.** An incoming
  object overwrites the local one only when the local one is not pending sync,
  or the incoming `mtime` is strictly newer:

  - `rslib/src/sync/collection/chunks.rs` `add_or_update_note_if_newer` and
    `add_or_update_card_if_newer` (the guard is
    `!existing.usn.is_pending_sync(pending_usn) || existing.mtime < entry.mtime`).

- **tags union / deletions via graves.** `rslib/src/sync/collection/changes.rs`
  `merge_tags` registers every incoming tag; `graves.rs` `apply_graves` removes
  by id.

## Offline then sync (why nothing is lost)

The engine is offline-first. Each device keeps a local SQLite collection and
records changes with an update sequence number (USN); locally pending rows carry
`usn = -1`. A device can review fully offline. On reconnect, `SyncCollection`
runs the normal flow (graves, then unchunked changes, then chunked
notes/cards/revlog both directions, then a sanity check). Because reviews and
Attempt events union by id, the offline work from both devices merges without
loss. If a device has never synced or is too far out of step, the engine falls
back to a one-way full sync (upload or download), which is safe by construction.

## Spec mapping (7b) and pgrep tests

- **7b, different cards offline on two devices.** Review distinct cards on the
  phone and the desktop while offline, then sync both. All reviews land
  (revlog union). Proven by `pylib/tests/test_pgrep_sync_roundtrip.py`.
- **7b, same card on both devices.** Review the same card on both, then sync.
  The newer-`mtime` scheduling state wins. Proven by the same test.
- **Attempt-log union.** Append Attempt events on two devices (distinct ids, and
  a repeated id), sync, and confirm the union with no duplication. Proven by the
  same test.
- **Offline then sync.** A device makes local changes while pointed at no
  server, then syncs. The changes land. Proven by the same test.

The host that these tests and the apps sync against is the self-hosted
`anki-sync-server` described in `docs_pgrep/plan/dev-harness.md` (the
`just sync-server` recipe). Point clients at it with a custom sync URL; auth is
`SYNC_USER1=user:pass`. No AnkiWeb dependency.
