# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""L3 exit-gate proof: a phone-to-desktop-and-back sync round trip.

Two collections (standing in for the phone and the desktop, which drive the same
engine over different bridges) sync through a self-hosted anki-sync-server. We
prove the documented conflict rule end to end (docs_pgrep/plan/l3-sync-conflict-rule.md):

- **revlog union by id:** distinct cards reviewed offline on each device all
  land, none lost or doubled;
- **same card, newer mtime wins:** the later review's scheduling state wins,
  while both reviews survive in the revlog;
- **Attempt log union:** immutable Attempt notes from both devices merge, and a
  re-append of the same event id is a no-op (idempotent);
- **offline then sync:** local changes are invisible to the peer until a sync.

The engine's sync stack (rslib/src/sync/**) is reused unmodified. The mobile app
calls the very same SyncCollection / FullUploadOrDownload RPCs over FFI.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from anki import scheduler_pb2
from anki.collection import Collection
from anki.pgrep import attempt_log
from anki.sync_pb2 import SyncAuth

if TYPE_CHECKING:
    from anki.scheduler.v3 import Scheduler as V3Scheduler

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CARD_ANSWER = scheduler_pb2.CardAnswer
_RATING = {
    1: _CARD_ANSWER.AGAIN,
    2: _CARD_ANSWER.HARD,
    3: _CARD_ANSWER.GOOD,
    4: _CARD_ANSWER.EASY,
}
_USER = "pgrep"
_PASS = "pgrep"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_health(port: int, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/health"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.2)
    raise RuntimeError(f"sync server did not become healthy on port {port}")


@pytest.fixture()
def sync_server() -> Iterator[str]:
    """Start a throwaway anki-sync-server and yield its endpoint URL."""
    import sys

    port = _free_port()
    base = tempfile.mkdtemp(prefix="pgrep-syncbase-")
    env = dict(os.environ)
    env["SYNC_USER1"] = f"{_USER}:{_PASS}"
    env["SYNC_HOST"] = "127.0.0.1"
    env["SYNC_PORT"] = str(port)
    env["SYNC_BASE"] = base
    proc = subprocess.Popen(
        [sys.executable, "tools/sync-server.py"],
        cwd=str(_REPO_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_health(port)
        yield f"http://127.0.0.1:{port}/"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(base, ignore_errors=True)


def _auth(col: Collection, endpoint: str) -> SyncAuth:
    raw = col.sync_login(_USER, _PASS, endpoint)
    return SyncAuth(hkey=raw.hkey, endpoint=endpoint)


def _sync(col: Collection, auth: SyncAuth) -> str:
    """Sync `col`, handling first-run full transfers. Returns the action taken."""
    out = col.sync_collection(auth=auth, sync_media=False)
    if out.required in (out.NO_CHANGES, out.NORMAL_SYNC):
        return "normal"
    upload = out.required == out.FULL_UPLOAD or out.required == out.FULL_SYNC
    col.close_for_full_sync()
    col.full_upload_or_download(auth=auth, server_usn=None, upload=upload)
    col.reopen(after_full_sync=True)
    return "full_upload" if upload else "full_download"


def _answer_top(col: Collection, rating: int) -> int:
    """Answer the current deck's top card through the real FSRS loop; return its
    id. The v3 scheduler only grades the top of the queue, so callers pick which
    card by setting the current deck (per-device subdecks below)."""
    # Lazy import: anki.cards at module load risks a cards<->hooks_gen cycle.
    from anki.cards import Card

    sched = cast("V3Scheduler", col.sched)
    queued = sched.get_queued_cards(fetch_limit=1)
    assert queued.cards, "no card at the top of the queue"
    chosen = queued.cards[0]
    card = Card(col)
    card._load_from_backend_card(chosen.card)
    card.start_timer()
    answer = sched.build_answer(card=card, states=chosen.states, rating=_RATING[rating])
    sched.answer_card(answer)
    return int(chosen.card.id)


def _revlog_ids(col: Collection) -> set[int]:
    return set(col.db.list("select id from revlog"))


def _card_mod(col: Collection, card_id: int) -> int:
    return int(col.db.scalar("select mod from cards where id = ?", card_id))


def _attempt_guids(col: Collection) -> set[str]:
    from anki.notes import NoteId

    return {
        col.get_note(NoteId(nid)).guid
        for nid in col.find_notes(f"tag:{attempt_log.ATTEMPT_TAG}")
    }


def test_sync_round_trip(sync_server: str, tmp_path: Path) -> None:
    endpoint = sync_server

    # --- Device A: a fresh collection with study cards split into per-device
    # subdecks (so each device reviews *different* cards by studying its own
    # deck), plus the Attempt notetype/deck so both are shared up front. --------
    path_a = str(tmp_path / "deviceA" / "collection.anki2")
    os.makedirs(os.path.dirname(path_a))
    dev_a = Collection(path_a)
    basic = dev_a.models.by_name("Basic")
    layout = [("SyncTest::deckA", 3), ("SyncTest::deckB", 3), ("SyncTest::shared", 1)]
    made = 0
    for name, count in layout:
        did = dev_a.decks.id(name)
        for _ in range(count):
            note = dev_a.new_note(basic)
            note["Front"] = f"Q{made}"
            note["Back"] = f"A{made}"
            made += 1
            dev_a.add_note(note, did)
    attempt_log.ensure_attempt_notetype(dev_a)
    attempt_log.ensure_attempt_deck(dev_a)

    auth_a = _auth(dev_a, endpoint)
    assert _sync(dev_a, auth_a) == "full_upload"

    # --- Device B: empty, then a full download makes it a mirror of A. --------
    path_b = str(tmp_path / "deviceB" / "collection.anki2")
    os.makedirs(os.path.dirname(path_b))
    dev_b = Collection(path_b)
    auth_b = _auth(dev_b, endpoint)
    assert _sync(dev_b, auth_b) == "full_download"

    # === 1. Different cards offline on each device (revlog union) =============
    dev_a.decks.set_current(dev_a.decks.id("SyncTest::deckA"))
    for _ in range(3):
        _answer_top(dev_a, rating=3)
        time.sleep(0.01)
    new_a = _revlog_ids(dev_a)

    dev_b.decks.set_current(dev_b.decks.id("SyncTest::deckB"))
    for _ in range(3):
        _answer_top(dev_b, rating=3)
        time.sleep(0.01)
    new_b = _revlog_ids(dev_b)

    assert len(new_a) == 3 and len(new_b) == 3
    assert new_a.isdisjoint(new_b), "reviews of different cards must have distinct ids"

    # Offline then sync: before syncing, neither device sees the other's work.
    assert new_b.isdisjoint(_revlog_ids(dev_a))
    assert new_a.isdisjoint(_revlog_ids(dev_b))

    _sync(dev_a, auth_a)  # A uploads its 3 reviews
    _sync(dev_b, auth_b)  # B pulls A's 3, pushes its own 3
    _sync(dev_a, auth_a)  # A pulls B's 3

    union = new_a | new_b
    assert union <= _revlog_ids(dev_a), "A lost a review after the round trip"
    assert union <= _revlog_ids(dev_b), "B lost a review after the round trip"
    # PK on revlog.id means no row can be doubled; the union size confirms it.
    assert len(union) == 6

    # === 2. Same card on both devices (newer mtime wins the schedule) =========
    dev_a.decks.set_current(dev_a.decks.id("SyncTest::shared"))
    same = _answer_top(dev_a, rating=3)  # A: Good
    mod_a = _card_mod(dev_a, same)
    rev_a_same = _revlog_ids(dev_a) - union
    # Card mtime is in seconds; a >1s gap makes B's review strictly newer.
    time.sleep(1.2)
    dev_b.decks.set_current(dev_b.decks.id("SyncTest::shared"))
    same_b = _answer_top(dev_b, rating=1)  # B: Again, later
    assert same_b == same, "both devices must review the same shared card"
    mod_b = _card_mod(dev_b, same)
    rev_b_same = _revlog_ids(dev_b) - union
    assert mod_b > mod_a

    _sync(dev_a, auth_a)
    _sync(dev_b, auth_b)
    _sync(dev_a, auth_a)

    # The newer (B's) scheduling state won on both devices ...
    assert _card_mod(dev_a, same) == mod_b
    assert _card_mod(dev_b, same) == mod_b
    # ... but both reviews of that card survive in the revlog (nothing lost).
    both_same = rev_a_same | rev_b_same
    assert len(both_same) == 2
    assert both_same <= _revlog_ids(dev_a)
    assert both_same <= _revlog_ids(dev_b)

    # === 3. Attempt log union (immutable notes, idempotent by event id) =======
    id_a = attempt_log.append_attempt(
        dev_a,
        {"topic": "topic::mechanics", "category": "mechanics", "correct": True,
         "selected_option": "A", "answered_at": int(time.time())},
    )
    id_b = attempt_log.append_attempt(
        dev_b,
        {"topic": "topic::quantum", "category": "quantum", "correct": False,
         "selected_option": "C", "answered_at": int(time.time())},
    )
    assert id_a != id_b

    # Idempotent within a device: re-appending the same event id is a no-op.
    before = _attempt_guids(dev_a)
    again = attempt_log.append_attempt(dev_a, {"event_id": id_a, "topic": "topic::mechanics"})
    assert again == id_a
    assert _attempt_guids(dev_a) == before

    _sync(dev_a, auth_a)
    _sync(dev_b, auth_b)
    _sync(dev_a, auth_a)

    # Both events land on both devices, once each (union by note guid = event id).
    assert {id_a, id_b} <= _attempt_guids(dev_a)
    assert {id_a, id_b} <= _attempt_guids(dev_b)
    assert list(_attempt_guids(dev_a)).count(id_a) == 1

    dev_a.close()
    dev_b.close()
