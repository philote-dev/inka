# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Crash / corruption test for the pgrep collection (spec section 7g).

Opens a fresh pgrep collection, then simulates killing the app mid-review 20
times in a row. Each iteration spawns a small child process that reviews cards
through the real FSRS scheduler and ``fsync``s every committed review's card id
to a sidecar log. The parent waits until the child is genuinely mid-review, then
``SIGKILL``s it with no clean close. The parent reopens the collection and:

    - runs SQLite ``pragma integrity_check`` (low-level corruption check),
    - runs Anki's ``check_database`` fsck (``col.fix_integrity``),
    - asserts every review the child durably committed is present in the revlog
      (no lost committed reviews), and that the revlog count never regresses.

Anki's Rust backend commits each ``answer_card`` in its own durable SQLite
transaction, so a review whose ``answer_card`` returned is guaranteed on disk
even under ``SIGKILL``. The sidecar therefore lower-bounds what must survive.

Prints a summary and exits non-zero on any corruption or lost review. Headless.

Run it with the built interpreter, for example::

    out/pyenv/bin/python tools/pgrep_crash_test.py --iters 20 --cards 8000
"""

from __future__ import annotations

import argparse
import os
import random
import signal
import subprocess
import sys
import tempfile
import time

# Importing this first makes ``anki`` importable from out/pylib (see the module).
import pgrep_synth

DECK_NAME = "PGRE::Bench"

# How long to wait for the child to commit its first review before giving up on a
# mid-review kill for that iteration (seconds).
FIRST_REVIEW_TIMEOUT = 8.0

# After the child is mid-review, wait a random slice in this range, then SIGKILL,
# so kills land at varied points inside the review loop (seconds). Kept short so
# the 20 kills together stay well under the 9999/day review budget (otherwise a
# late child would find an empty queue and not be killed mid-review).
KILL_DELAY_RANGE = (0.01, 0.08)


# --- child: review until killed, fsync each committed review -----------------


def run_child(path: str, sidecar: str, deck_name: str) -> None:
    """Open the collection and answer cards forever, fsync-logging each commit.

    Exits only if the queue empties; normally the parent ``SIGKILL``s it first.
    """
    # Import order matters: anki.collection must load before anki.cards, or the
    # cards <-> hooks_gen circular import trips when cards is imported first. The
    # noqa keeps ruff's import sorter from reordering these back into the cycle.
    from anki.collection import Collection  # noqa: I001
    from anki.cards import Card
    from anki.decks import DeckId
    from anki.scheduler.v3 import CardAnswer

    col = Collection(path)
    deck_id = col.decks.id_for_name(deck_name)
    if deck_id is not None:
        col.decks.set_current(DeckId(deck_id))

    fd = os.open(sidecar, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    while True:
        top = col.sched.get_queued_cards(fetch_limit=1)  # type: ignore[union-attr]
        if not top.cards:
            break
        queued = top.cards[0]
        card = Card(col)
        card._load_from_backend_card(queued.card)
        card.start_timer()
        answer = col.sched.build_answer(  # type: ignore[union-attr]
            card=card, states=queued.states, rating=CardAnswer.GOOD
        )
        col.sched.answer_card(answer)  # type: ignore[union-attr]
        # Record the durably-committed review id AFTER answer_card returns, then
        # fsync, so every sidecar entry is guaranteed already on disk.
        os.write(fd, f"{queued.card.id}\n".encode())
        os.fsync(fd)
    os._exit(0)


# --- parent: build, kill loop, reopen + verify ------------------------------


def _read_sidecar(sidecar: str) -> list[int]:
    if not os.path.exists(sidecar):
        return []
    with open(sidecar, encoding="utf-8") as handle:
        return [int(line) for line in handle if line.strip()]


def _open_with_retry(path: str, retries: int = 5):
    """Open the collection, retrying briefly in case a killed child left a lock."""
    from anki.collection import Collection
    from anki.errors import DBError

    last: Exception | None = None
    for attempt in range(retries):
        try:
            return Collection(path)
        except DBError as err:  # pragma: no cover - transient after SIGKILL
            last = err
            time.sleep(0.1 * (attempt + 1))
    raise RuntimeError(f"could not reopen collection at {path}: {last}")


def reopen_and_check(path: str) -> dict:
    """Reopen the collection and run both integrity checks. Returns a result dict."""
    col = _open_with_retry(path)
    try:
        pragma = col.db.scalar("pragma integrity_check")
        fsck_msg, fsck_ok = col.fix_integrity()
        revlog_cids = set(col.db.list("select cid from revlog"))
        revlog_count = col.db.scalar("select count() from revlog")
        card_count = col.card_count()
    finally:
        col.close()
    return {
        "pragma_ok": pragma == "ok",
        "pragma": pragma,
        "fsck_ok": fsck_ok,
        "fsck_msg": fsck_msg.splitlines()[0] if fsck_msg else "",
        "revlog_cids": revlog_cids,
        "revlog_count": int(revlog_count or 0),
        "card_count": card_count,
    }


def run_parent(args: argparse.Namespace) -> int:
    rng = random.Random(args.seed)
    tmpdir = tempfile.mkdtemp(prefix="pgrep_crash_")
    path = os.path.join(tmpdir, "crash.anki2")
    child_env = {
        **os.environ,
        "PYTHONPATH": os.path.join(pgrep_synth.REPO_ROOT, "out", "pylib"),
    }

    print("pgrep crash / corruption test (spec section 7g)")
    print(
        f"  building fresh collection: {args.cards} cards (seed {args.seed}) ...",
        flush=True,
    )
    col, info = pgrep_synth.build_collection(
        path, args.cards, seed=args.seed, deck_name=DECK_NAME
    )
    col.close()
    print(
        f"  built: {info['card_count']} cards, {info['note_count']} notes; "
        f"simulating {args.iters} mid-review kills\n"
    )

    prev_count = 0
    clean_reopens = 0
    integrity_failures = 0
    lost_reviews_total = 0
    mid_review_kills = 0
    total_committed = 0
    per_iter: list[dict] = []

    for i in range(1, args.iters + 1):
        sidecar = os.path.join(tmpdir, f"progress_{i}.log")
        proc = subprocess.Popen(
            [
                sys.executable,
                os.path.abspath(__file__),
                "--child",
                path,
                sidecar,
                DECK_NAME,
            ],
            env=child_env,
        )

        # Wait until the child is genuinely mid-review (>=1 committed) or it exits.
        deadline = time.time() + FIRST_REVIEW_TIMEOUT
        while time.time() < deadline:
            if _read_sidecar(sidecar):
                break
            if proc.poll() is not None:
                break
            time.sleep(0.005)

        mid_review = False
        if proc.poll() is None and _read_sidecar(sidecar):
            # Child is alive and already reviewing: land the kill at a varied
            # point inside the review loop.
            time.sleep(rng.uniform(*KILL_DELAY_RANGE))
            if proc.poll() is None:
                os.kill(proc.pid, signal.SIGKILL)
                mid_review = True
                mid_review_kills += 1
        if not mid_review and proc.poll() is None:
            # Child never reached a mid-review state (didn't start, or finished the
            # queue). Not an abrupt kill, but still ensure it is gone.
            os.kill(proc.pid, signal.SIGKILL)
        proc.wait()

        committed = _read_sidecar(sidecar)
        result = reopen_and_check(path)

        integrity_ok = result["pragma_ok"] and result["fsck_ok"]
        missing = [cid for cid in committed if cid not in result["revlog_cids"]]
        lost = len(missing)
        regressed = result["revlog_count"] < prev_count

        if integrity_ok and not regressed:
            clean_reopens += 1
        if not integrity_ok:
            integrity_failures += 1
        lost_reviews_total += lost
        total_committed = result["revlog_count"]

        status = "OK" if (integrity_ok and lost == 0 and not regressed) else "FAIL"
        print(
            f"  kill {i:>2}/{args.iters}: committed>={len(committed):>4}  "
            f"revlog {prev_count:>5}->{result['revlog_count']:<5}  "
            f"pragma={result['pragma']}  fsck_ok={result['fsck_ok']}  "
            f"lost={lost}  mid_review={'yes' if mid_review else 'no '}  [{status}]"
        )

        per_iter.append(
            {
                "committed": len(committed),
                "lost": lost,
                "integrity_ok": integrity_ok,
                "regressed": regressed,
            }
        )
        prev_count = result["revlog_count"]

    # --- summary -------------------------------------------------------------

    all_clean = clean_reopens == args.iters
    no_lost = lost_reviews_total == 0
    no_integrity_fail = integrity_failures == 0
    # Sanity: the crash path must actually have been exercised. If no child ever
    # committed a review (e.g. a broken child or an exhausted pool), the run is
    # meaningless and must not be reported as a pass.
    exercised = total_committed > 0 and mid_review_kills == args.iters
    ok = all_clean and no_lost and no_integrity_fail and exercised

    print("\nsummary")
    print(f"  reopened clean:        {clean_reopens}/{args.iters}")
    print(
        f"  integrity OK:          {args.iters - integrity_failures}/{args.iters} "
        f"(pragma integrity_check + check_database)"
    )
    print(f"  genuine mid-review kills: {mid_review_kills}/{args.iters}")
    print(f"  committed reviews lost: {lost_reviews_total}")
    print(f"  reviews durably persisted (final revlog): {total_committed}")
    print(
        f"  review counts consistent: {'yes' if no_lost and no_integrity_fail else 'NO'}"
    )

    verdict = "PASS" if ok else "FAIL"
    if ok:
        detail = (
            f"{args.iters}/{args.iters} reopened clean, integrity OK, "
            "review counts consistent"
        )
    elif not exercised:
        detail = (
            "crash path not exercised "
            f"(mid-review kills {mid_review_kills}/{args.iters}, "
            f"committed {total_committed}); increase --cards"
        )
    else:
        detail = "corruption or lost reviews detected"
    print(f"\nRESULT: {verdict} - {detail}")

    if args.keep:
        print(f"\n(kept collection at {path})")
    else:
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)

    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="pgrep crash / corruption test")
    parser.add_argument(
        "--iters", type=int, default=20, help="number of mid-review kills"
    )
    parser.add_argument(
        "--cards",
        type=int,
        default=8000,
        help="synthetic review cards to build (needs enough for all kills)",
    )
    parser.add_argument("--seed", type=int, default=1234, help="deterministic RNG seed")
    parser.add_argument(
        "--keep", action="store_true", help="keep the temp collection dir"
    )
    args = parser.parse_args()
    if args.iters < 1:
        parser.error("--iters must be >= 1")
    return run_parent(args)


if __name__ == "__main__":
    # Child mode: `--child <path> <sidecar> <deck_name>`.
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        run_child(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        sys.exit(main())
