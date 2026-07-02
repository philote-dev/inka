# L1 Coordination — Shared topic-tag field + Attempt-log schema

**Status: coordination contract for Build Layer L1 (locked for this layer).**
This is the shared schema both L1 tracks build against so they don't collide:

- **L1.1 (Rust selector)** *consumes* the topic-tag format (to compute per-topic
  weakness/worth). It does **not** read the attempt log.
- **L1.2 (Data model)** *implements* the two-level topic tags on notes/cards and
  the attempt log as notes (notes-as-log, "A now, C-ready").

Sources: `feature-interleaving.md` (topic taxonomy, selector), `anki-rooting-and-rust.md`
(weakness = 1 − mean R; FSRS-native), `attempt-log-storage.md` (K1–K5, notes-as-log),
`overview.md` (PGRE blueprint).

---

## 1. Topic-tag contract (shared by both tracks)

Two-level hierarchical Anki tags (Anki uses `::` for hierarchy):

```
topic::<category>                     # category-level (required)
topic::<category>::<subtopic>         # optional finer level (big-3 only)
```

- **Category is required**; subtopics are optional and used only under the big-3
  (mechanics, electromagnetism, quantum) per `feature-interleaving.md`.
- **Casing:** lowercase; multi-word slugs use `snake_case`.
- A note/card MAY carry other, non-`topic::` tags; only `topic::*` tags are read here.

### Canonical category slugs + PGRE blueprint weights

Blueprint % is the PGRE's official topic percentages (stable 20+ yrs; `overview.md`).
**Worth uses category-level %** — subtopics inherit their category's weight.

| Category slug         | PGRE area              | blueprint % |
| --------------------- | ---------------------- | ----------: |
| `mechanics`           | Classical Mechanics    |          20 |
| `electromagnetism`    | Electromagnetism (E&M) |          18 |
| `quantum`             | Quantum Mechanics      |          13 |
| `thermodynamics`      | Thermo / Stat Mech     |          10 |
| `atomic`              | Atomic Physics         |          10 |
| `optics_waves`        | Optics & Waves         |           8 |
| `special_relativity`  | Special Relativity     |           6 |
| `lab`                 | Lab Methods            |           6 |
| `specialized`         | Specialized Topics     |           9 |

Sum = 100. Store as a fraction (e.g. `0.20`) or percent consistently within each
language; the table is duplicated per language (normal cross-language boundary
duplication — do **not** create a shared file for it).

### Parsing rules (identical semantics in Rust and Python)

Given a note/card's tags:

1. **Topic tags** = all tags equal to `topic` prefix `topic::…` (case-insensitive match on the `topic::` prefix).
2. **Category** = the 2nd `::`-segment of the topic tag (e.g. `topic::mechanics::lagrangian` → `mechanics`).
3. **Finest topic** = the full topic tag string (used for weakness aggregation at the finest tagged level).
4. **Blueprint%** is keyed by **category** (subtopics share their category's %).
5. **Variety / anti-blocking** counts at **category** level (soft preference to vary
   subtopics within the big-3 is out of scope for L1 — category-level is enough).
6. **Untagged / unknown category:** a card with no `topic::` tag (or an unrecognized
   category) is treated as `category = unknown`, `blueprint% = 0`.
   **Hard rule:** such a card is still gathered and ordered (sorted last by worth) —
   it is **never dropped** from the due set. The selector only reorders + truncates
   to the existing daily limit; it never removes a due card that stock Anki would show.
7. If a card somehow has multiple `topic::` tags, use the **first** one
   (deterministic; multi-topic items are out of scope for L1).

---

## 2. Weakness & Worth (selector-side; FSRS-native)

Per `anki-rooting-and-rust.md` (no attempt-log dependency for the selector):

- `weakness(topic) = 1 − mean(FSRS retrievability R) over that topic's DUE cards`,
  aggregated at the **finest tagged level**, cached once per queue build.
- `worth(card)   = blueprint%(category(card)) × weakness(topic(card))`.
- **Desirable-difficulty band:** prefer items with predicted success in **[0.60, 0.85]**
  (computed from FSRS R; no new model).
- **Anti-blocking:** at most **K = 3** consecutive same-**category** items (default; tunable).

The attempt log (below) feeds **Performance + calibration (L5)**, NOT the selector.

---

## 3. Attempt-log schema — notes-as-log ("A now, C-ready")

Per `attempt-log-storage.md` decision (A now, C-ready; B rejected). One immutable
note per problem-attempt event, riding Anki's free note sync.

### Notetype: `pgrep::Attempt`

One note = one event. Fields (order matters for Anki; field 1 is the sort field):

| # | Field         | Meaning                                                                 |
| - | ------------- | ---------------------------------------------------------------------- |
| 1 | `event_id`    | **= the note's GUID** (K2). Canonical event identity; every fold keys on it. |
| 2 | `event_json`  | Single JSON blob (K3): the full immutable payload — see below.          |
| 3 | `topic`       | Denormalized hot filter: the item's finest `topic::…` value.            |
| 4 | `correct`     | Denormalized: `"1"` / `"0"`.                                            |
| 5 | `answered_at` | Denormalized: unix epoch seconds (UTC) as a string.                    |

`event_json` payload (superset; keep it self-contained — no external joins, K1):

```json
{
  "event_id": "<= note guid>",
  "schema": 1,
  "item_card_id": 0,
  "item_note_id": 0,
  "topic": "topic::mechanics::lagrangian",
  "category": "mechanics",
  "correct": true,
  "selected_option": "C",
  "ladder_depth": 0,
  "subgoal_productions": [],
  "session_id": "<uuid>",
  "answered_at": 1780000000,
  "latency_ms": 0,
  "device": "<hlc/device id>"
}
```

### Storage / placement

- Attempt notes' auto-spawned cards live in a dedicated **suspended, hidden deck**
  `pgrep::attempt-log`, excluded from study/search/stats (the known, contained
  notes-as-log cost — Anki forces ≥1 card per note).
- Each attempt note is **tagged** `pgrep::attempt` **plus** the item's `topic::…` tag
  (cheap tag-search pre-filter — K3).

### Invariants (build these in from day one)

- **K1 Immutable, self-contained:** never edit an attempt note after creation;
  `event_json` carries everything the fold needs.
- **K2 Identity = note guid:** `event_id` field mirrors the note GUID; folds/caches
  key on it (idempotent rebuild, union-by-id dedup, consistent with the documented
  sync conflict rule).
- **K3 Payload = one JSON blob + a few flat fields** (`topic`, `correct`, `answered_at`)
  + topic on tags. A parses JSON on demand; C would parse the *same* JSON into cache rows.
- **K4 One read-model seam:** ALL attempt analytics go through a single interface —
  `attempts(topic, window) -> [Event]` and `performance_fold(topic, window) -> stats`.
  Callers (Performance L5, calibration dashboard) never touch storage directly.
- **K5 Cache = fold(all Attempt notes), local-only, never synced, recomputable.**
  Defined now, **built later** (deferred). Do not add any synced table; never touch
  `rslib/src/sync/**`.

### Append is idempotent on `event_id`

Appending an event whose `event_id` already exists is a **no-op** (do not create a
duplicate, do not mutate the existing note). This keeps the fold union-by-id clean.

---

## 4. File-ownership boundaries (so the two ∥ tracks never touch the same file)

**L1.1 (Rust selector) owns:**
- `proto/anki/deck_config.proto` (+ `proto/anki/scheduler.proto` only if a config RPC is added)
- `rslib/src/**` (selector, gather, scorer module, service impl)
- NEW Python test: `pylib/tests/test_pgrep_selector.py`
- **Must NOT** edit `pylib/anki/collection.py` or anything under `pylib/anki/pgrep/**`.
  Reach the new backend behavior in the Python test via the deck-config proto +
  `get_queued_cards` (no hand-written wrapper needed).

**L1.2 (Data model) owns:**
- NEW package `pylib/anki/pgrep/**` (e.g. `tags.py`, `blueprint.py`, `attempt_log.py`)
- NEW Python tests: `pylib/tests/test_pgrep_tags.py`, `pylib/tests/test_pgrep_attempt_log.py`
- **Must NOT** edit `proto/**`, `rslib/**`, or `pylib/tests/test_pgrep_selector.py`.

**Shared static data** (blueprint table, category slugs) is duplicated per language
from this doc — no shared file, no cross-track import.
