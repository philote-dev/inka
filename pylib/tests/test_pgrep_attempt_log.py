# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the attempt log (notes-as-log) and its read-model seam (L1.2).

Contract: docs/pgrep/planning/l1-coordination-schema.md §3 (K1-K5 + idempotency).
These tests use real Anki notes/cards (no mocks).
"""

from __future__ import annotations

import json
import time

from anki.consts import QUEUE_TYPE_SUSPENDED
from anki.notes import NoteId
from anki.pgrep.attempt_log import (
    ATTEMPT_DECK_NAME,
    ATTEMPT_NOTETYPE_NAME,
    ATTEMPT_TAG,
    append_attempt,
    attempts,
    ensure_attempt_notetype,
    get_attempt_notetype,
    performance_fold,
)
from tests.shared import getEmptyCol


def _attempt_note_ids(col) -> list[NoteId]:
    notetype = get_attempt_notetype(col)
    if not notetype:
        return []
    return list(col.models.nids(notetype))


def _only_attempt_note(col):
    ids = _attempt_note_ids(col)
    assert len(ids) == 1
    return col.get_note(ids[0])


# Bootstrap
##########################################################################


def test_ensure_notetype_creates_expected_fields_once():
    col = getEmptyCol()
    assert get_attempt_notetype(col) is None
    notetype = ensure_attempt_notetype(col)
    assert notetype["name"] == ATTEMPT_NOTETYPE_NAME
    assert col.models.field_names(notetype) == [
        "event_id",
        "event_json",
        "topic",
        "correct",
        "answered_at",
    ]
    # event_id is the sort field (field 1)
    assert notetype["sortf"] == 0
    # idempotent: calling again returns the same notetype, not a duplicate
    again = ensure_attempt_notetype(col)
    assert again["id"] == notetype["id"]
    names = [nt.name for nt in col.models.all_names_and_ids()]
    assert names.count(ATTEMPT_NOTETYPE_NAME) == 1


# Append: identity, payload, flat fields, tags (K1-K3)
##########################################################################


def test_append_sets_event_id_to_guid_and_roundtrips_payload():
    col = getEmptyCol()
    event = {
        "topic": "topic::mechanics::lagrangian",
        "correct": True,
        "selected_option": "C",
        "ladder_depth": 0,
        "subgoal_productions": [],
        "session_id": "sess-1",
        "answered_at": 1780000000,
        "latency_ms": 4200,
        "device": "dev-1",
    }
    event_id = append_attempt(col, event)

    note = _only_attempt_note(col)
    # K2: event_id field mirrors the note guid, and is the returned id
    assert event_id == note.guid
    assert note["event_id"] == note.guid

    # event_json round-trips the payload (K1 self-contained)
    parsed = json.loads(note["event_json"])
    assert parsed["event_id"] == note.guid
    assert parsed["schema"] == 1
    assert parsed["topic"] == "topic::mechanics::lagrangian"
    assert parsed["category"] == "mechanics"  # derived
    assert parsed["correct"] is True
    assert parsed["answered_at"] == 1780000000
    assert parsed["selected_option"] == "C"
    assert parsed["subgoal_productions"] == []
    assert parsed["session_id"] == "sess-1"
    assert parsed["latency_ms"] == 4200

    # flat denormalized fields (K3)
    assert note["topic"] == "topic::mechanics::lagrangian"
    assert note["correct"] == "1"
    assert note["answered_at"] == "1780000000"

    # tags: pgrep::attempt + the item's topic tag (K3 pre-filter)
    assert note.has_tag(ATTEMPT_TAG)
    assert note.has_tag("topic::mechanics::lagrangian")


def test_append_incorrect_and_untagged():
    col = getEmptyCol()
    append_attempt(col, {"correct": False, "answered_at": 100})
    note = _only_attempt_note(col)
    assert note["correct"] == "0"
    assert note["topic"] == ""
    assert note.has_tag(ATTEMPT_TAG)
    # no topic tag beyond the attempt marker
    assert [t for t in note.tags if t.startswith("topic::")] == []


def test_append_honours_supplied_event_id_as_guid():
    col = getEmptyCol()
    supplied = "attempt-guid-fixed-0001"
    event_id = append_attempt(
        col,
        {"event_id": supplied, "topic": "topic::quantum", "correct": True},
    )
    assert event_id == supplied
    note = _only_attempt_note(col)
    assert note.guid == supplied
    assert note["event_id"] == supplied


# Storage: suspended, hidden deck, excluded from study (contract §3 placement)
##########################################################################


def test_attempt_card_is_suspended_in_hidden_deck_and_out_of_queue():
    col = getEmptyCol()

    # a real study card in the Default deck, to prove the queue still serves it
    default_did = col.decks.id("Default")
    normal = col.new_note(col.models.by_name("Basic"))
    normal["Front"] = "q"
    normal["Back"] = "a"
    col.add_note(normal, default_did)
    normal_cid = normal.cards()[0].id

    append_attempt(col, {"topic": "topic::mechanics", "correct": True})
    note = _only_attempt_note(col)
    card = note.cards()[0]

    attempt_did = col.decks.id(ATTEMPT_DECK_NAME)
    # suspended AND in the hidden deck
    assert card.queue == QUEUE_TYPE_SUSPENDED
    assert card.did == attempt_did
    assert col.find_cards(f"deck:{ATTEMPT_DECK_NAME}") == [card.id]
    assert card.id in col.find_cards("is:suspended")

    # with the Default deck selected, the queue serves the normal card, never
    # the suspended attempt card
    col.decks.select(default_did)
    queued = col.sched.get_queued_cards(fetch_limit=50)
    queued_ids = [qc.card.id for qc in queued.cards]
    assert normal_cid in queued_ids
    assert card.id not in queued_ids

    # even with the attempt-log deck itself selected, nothing is study-able
    col.decks.select(attempt_did)
    empty = col.sched.get_queued_cards(fetch_limit=50)
    assert list(empty.cards) == []
    assert (empty.new_count, empty.learning_count, empty.review_count) == (0, 0, 0)


# Idempotency + immutability (K1 + append idempotent on event_id)
##########################################################################


def test_append_is_idempotent_on_event_id():
    col = getEmptyCol()
    first = append_attempt(
        col,
        {
            "event_id": "dup-1",
            "topic": "topic::mechanics",
            "correct": True,
            "answered_at": 1000,
        },
    )
    note_before = _only_attempt_note(col)
    json_before = note_before["event_json"]
    mod_before = note_before.mod
    guid_before = note_before.guid

    # same event_id, DIFFERENT payload -> must be a no-op (no dup, no mutation)
    second = append_attempt(
        col,
        {
            "event_id": "dup-1",
            "topic": "topic::mechanics",
            "correct": False,
            "answered_at": 9999,
        },
    )
    assert first == second == "dup-1"

    # still exactly one note, byte-identical, unmodified
    assert len(_attempt_note_ids(col)) == 1
    note_after = _only_attempt_note(col)
    assert note_after.guid == guid_before
    assert note_after["event_json"] == json_before
    assert note_after["correct"] == "1"  # original value retained
    assert note_after.mod == mod_before


def test_append_never_mutates_existing_notes():
    col = getEmptyCol()
    append_attempt(
        col,
        {
            "event_id": "a",
            "topic": "topic::mechanics",
            "correct": True,
            "answered_at": 1,
        },
    )
    note_a_id = _attempt_note_ids(col)[0]
    note_a = col.get_note(note_a_id)
    json_a = note_a["event_json"]
    mod_a = note_a.mod

    # append several more, different events
    append_attempt(
        col,
        {
            "event_id": "b",
            "topic": "topic::quantum",
            "correct": False,
            "answered_at": 2,
        },
    )
    append_attempt(
        col,
        {"event_id": "c", "topic": "topic::atomic", "correct": True, "answered_at": 3},
    )

    assert len(_attempt_note_ids(col)) == 3
    reloaded = col.get_note(note_a_id)
    assert reloaded["event_json"] == json_a
    assert reloaded.mod == mod_a


# Read-model seam (K4): attempts() + performance_fold()
##########################################################################


def _seed_events(col) -> None:
    append_attempt(
        col,
        {
            "event_id": "m1",
            "topic": "topic::mechanics",
            "correct": True,
            "answered_at": 1000,
        },
    )
    append_attempt(
        col,
        {
            "event_id": "m2",
            "topic": "topic::mechanics::lagrangian",
            "correct": False,
            "answered_at": 2000,
        },
    )
    append_attempt(
        col,
        {
            "event_id": "q1",
            "topic": "topic::quantum::spin",
            "correct": True,
            "answered_at": 3000,
        },
    )
    append_attempt(
        col,
        {
            "event_id": "q2",
            "topic": "topic::quantum",
            "correct": True,
            "answered_at": 4000,
        },
    )


def test_attempts_returns_all_sorted_by_time():
    col = getEmptyCol()
    _seed_events(col)
    got = attempts(col)
    assert [e.event_id for e in got] == ["m1", "m2", "q1", "q2"]
    # parsed from event_json into Event objects
    assert got[0].topic == "topic::mechanics"
    assert got[0].category == "mechanics"
    assert got[0].correct is True
    assert got[1].correct is False


def test_attempts_filters_by_topic_hierarchically():
    col = getEmptyCol()
    _seed_events(col)
    # exact + descendant match
    quantum = attempts(col, topic="topic::quantum")
    assert sorted(e.event_id for e in quantum) == ["q1", "q2"]
    mechanics = attempts(col, topic="topic::mechanics")
    assert sorted(e.event_id for e in mechanics) == ["m1", "m2"]
    # exact leaf match only
    spin = attempts(col, topic="topic::quantum::spin")
    assert [e.event_id for e in spin] == ["q1"]


def test_attempts_filters_by_window_range():
    col = getEmptyCol()
    _seed_events(col)
    # [start, end): inclusive start, exclusive end
    mid = attempts(col, window=(1500, 3500))
    assert [e.event_id for e in mid] == ["m2", "q1"]
    # open-ended lower bound
    early = attempts(col, window=(None, 2500))
    assert [e.event_id for e in early] == ["m1", "m2"]
    # topic + window combined
    late_quantum = attempts(col, topic="topic::quantum", window=(3500, None))
    assert [e.event_id for e in late_quantum] == ["q2"]


def test_attempts_window_seconds_lookback():
    col = getEmptyCol()
    now = int(time.time())
    append_attempt(
        col,
        {
            "event_id": "recent",
            "topic": "topic::mechanics",
            "correct": True,
            "answered_at": now - 10,
        },
    )
    append_attempt(
        col,
        {
            "event_id": "old",
            "topic": "topic::mechanics",
            "correct": True,
            "answered_at": now - 100000,
        },
    )
    recent = attempts(col, window=120)
    assert [e.event_id for e in recent] == ["recent"]
    assert len(attempts(col)) == 2


def test_performance_fold_aggregates_per_topic():
    col = getEmptyCol()
    _seed_events(col)
    fold = performance_fold(col)
    assert fold.total == 4
    assert fold.correct == 3
    assert fold.accuracy == 0.75
    assert fold.by_topic["topic::mechanics"].correct == 1
    assert fold.by_topic["topic::mechanics"].total == 1
    assert fold.by_topic["topic::mechanics"].accuracy == 1.0
    assert fold.by_topic["topic::mechanics::lagrangian"].correct == 0
    assert fold.by_topic["topic::mechanics::lagrangian"].accuracy == 0.0


def test_performance_fold_respects_topic_and_window():
    col = getEmptyCol()
    _seed_events(col)
    quantum = performance_fold(col, topic="topic::quantum")
    assert quantum.total == 2
    assert quantum.correct == 2
    assert quantum.accuracy == 1.0

    windowed = performance_fold(col, window=(None, 2500))
    assert windowed.total == 2
    assert windowed.correct == 1
    assert windowed.accuracy == 0.5


def test_seam_empty_when_no_attempts():
    col = getEmptyCol()
    assert attempts(col) == []
    fold = performance_fold(col)
    assert fold.total == 0
    assert fold.correct == 0
    assert fold.accuracy == 0.0
    assert fold.by_topic == {}


# Undo-safety (nice-to-have): append is a single undoable action
##########################################################################


def test_append_attempt_is_undoable():
    col = getEmptyCol()
    append_attempt(
        col,
        {
            "event_id": "u1",
            "topic": "topic::mechanics",
            "correct": True,
            "answered_at": 1,
        },
    )
    assert len(_attempt_note_ids(col)) == 1
    cards_before = col.card_count()

    col.undo()

    # the note + its card are gone, and the collection is consistent
    assert len(_attempt_note_ids(col)) == 0
    assert col.card_count() == cards_before - 1
    orphans = col.db.scalar(
        "select count() from cards where nid not in (select id from notes)"
    )
    assert orphans == 0
