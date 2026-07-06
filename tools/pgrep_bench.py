# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""One-command latency benchmark for the pgrep engine (spec section 7h + 10).

Builds (or loads) a large synthetic Anki collection, injects a demo study history
so the scores compute, then measures p50 / p95 / worst-case latency over many
iterations for each hot action:

    - next_card           get the next card from the scheduler (spec: p95 < 100ms)
    - answer_card         grade a card through the real FSRS scheduler
    - memory_score        Memory compute
    - performance_score   Performance compute
    - readiness_score     Readiness compute
    - coverage            Coverage compute
    - dashboard_refresh   all four scores, warm caches (spec: p95 < 500ms)
    - dashboard_first_load all four scores, cold backend (spec: p95 < 1s)

It prints a table per action and a one-line pass/fail against the three spec
targets it can measure. Everything is headless (no GUI) and deterministic given
``--seed``.

Run it with the built interpreter, for example::

    out/pyenv/bin/python tools/pgrep_bench.py --cards 5000 --iters 300

``--cards`` accepts up to 50000. The build itself is timed and reported, so an
honest picture of both setup and steady-state latency is shown.
"""

from __future__ import annotations

import argparse
import gc
import math
import sys
import tempfile
import time
from typing import Callable, cast

# Importing this first makes ``anki`` importable from out/pylib (see the module).
import pgrep_synth

MAX_CARDS = 50000

# Spec targets (section 7h / 10). Only the three below are measurable here.
TARGET_NEXT_CARD_MS = 100.0
TARGET_FIRST_LOAD_MS = 1000.0
TARGET_REFRESH_MS = 500.0


def percentile(values: list[float], pct: float) -> float:
    """Linear-interpolation percentile (like numpy's default), ``pct`` in [0,100]."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (pct / 100.0)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[int(rank)]
    return ordered[low] * (high - rank) + ordered[high] * (rank - low)


def measure(fn: Callable[[], object], iters: int, warmup: int = 1) -> list[float]:
    """Return ``iters`` per-call latencies (ms) for ``fn``, after ``warmup`` calls.

    GC is disabled during timing so a stray collection does not spike a sample;
    it is restored afterwards.
    """
    for _ in range(warmup):
        fn()
    samples: list[float] = []
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        for _ in range(iters):
            start = time.perf_counter()
            fn()
            samples.append((time.perf_counter() - start) * 1000.0)
    finally:
        if gc_was_enabled:
            gc.enable()
    return samples


class Bench:
    """Holds the built collection and the callables under test."""

    def __init__(self, path: str, cards: int, seed: int):
        self.path = path
        self.cards = cards
        self.seed = seed
        self.col, self.info = pgrep_synth.build_collection(path, cards, seed=seed)

        from anki.cards import Card
        from anki.pgrep import coverage, memory, performance, readiness
        from anki.scheduler.v3 import CardAnswer

        self._Card = Card
        self._CardAnswer = CardAnswer
        self._memory = memory
        self._performance = performance
        self._readiness = readiness
        self._coverage = coverage

    # --- individual actions --------------------------------------------------

    def next_card(self) -> object:
        # Idempotent: reads the top of the queue without consuming it.
        return self.col.sched.get_queued_cards(fetch_limit=1)

    def answer_top_card(self) -> bool:
        """Grade the current top card (consumes one due card). Returns success."""
        top = self.col.sched.get_queued_cards(fetch_limit=1)
        if not top.cards:
            return False
        queued = top.cards[0]
        card = self._Card(self.col)
        card._load_from_backend_card(queued.card)
        card.start_timer()
        answer = self.col.sched.build_answer(
            card=card, states=queued.states, rating=self._CardAnswer.GOOD
        )
        self.col.sched.answer_card(answer)
        return True

    def memory_score(self) -> object:
        return self._memory.memory_score(self.col)

    def performance_score(self) -> object:
        return self._performance.performance_score(self.col)

    def readiness_score(self) -> object:
        return self._readiness.readiness_score(self.col)

    def coverage(self) -> object:
        return self._coverage.coverage(self.col)

    def dashboard(self) -> tuple[object, object, object, object]:
        """Everything the dashboard needs: all four scores, as the surfaces call them."""
        return (
            self._memory.memory_score(self.col),
            self._performance.performance_score(self.col),
            self._readiness.readiness_score(self.col),
            self._coverage.coverage(self.col),
        )

    # --- answer loop (bounded by the available due pool) ---------------------

    def measure_answers(self, iters: int) -> list[float]:
        samples: list[float] = []
        gc_was_enabled = gc.isenabled()
        gc.disable()
        try:
            for _ in range(iters):
                top = self.col.sched.get_queued_cards(fetch_limit=1)
                if not top.cards:
                    break
                queued = top.cards[0]
                card = self._Card(self.col)
                card._load_from_backend_card(queued.card)
                card.start_timer()
                answer = self.col.sched.build_answer(
                    card=card, states=queued.states, rating=self._CardAnswer.GOOD
                )
                start = time.perf_counter()
                self.col.sched.answer_card(answer)
                samples.append((time.perf_counter() - start) * 1000.0)
        finally:
            if gc_was_enabled:
                gc.enable()
        return samples

    # --- cold "first load": recompute the dashboard on a fresh backend -------

    def measure_first_load(self, reopens: int) -> list[float]:
        from anki.collection import Collection
        from anki.pgrep import coverage, memory, performance, readiness

        samples: list[float] = []
        self.col.close()
        try:
            for _ in range(reopens):
                col = Collection(self.path)  # fresh backend => cold caches
                start = time.perf_counter()
                memory.memory_score(col)
                performance.performance_score(col)
                readiness.readiness_score(col)
                coverage.coverage(col)
                samples.append((time.perf_counter() - start) * 1000.0)
                col.close()
        finally:
            # Reopen so the object is usable again for any later teardown.
            self.col = Collection(self.path)
        return samples


def format_row(name: str, samples: list[float]) -> str:
    if not samples:
        return f"{name:<22}{'n/a':>11}{'n/a':>11}{'n/a':>12}{0:>7}"
    p50 = percentile(samples, 50)
    p95 = percentile(samples, 95)
    worst = max(samples)
    return f"{name:<22}{p50:>11.2f}{p95:>11.2f}{worst:>12.2f}{len(samples):>7}"


def target_line(label: str, value: float, threshold: float, unit: str = "ms") -> str:
    ok = value < threshold
    tag = "PASS" if ok else "FAIL"
    return (
        f"  [{tag}] {label:<26} = {value:8.2f} {unit}   "
        f"(target < {threshold:.0f} {unit})"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="pgrep engine latency benchmark")
    parser.add_argument(
        "--cards",
        type=int,
        default=5000,
        help=f"number of synthetic pgrep cards to generate (max {MAX_CARDS})",
    )
    parser.add_argument(
        "--iters",
        type=int,
        default=300,
        help="timed iterations per action (default 300)",
    )
    parser.add_argument(
        "--reopens",
        type=int,
        default=15,
        help="cold reopens for the dashboard first-load measurement (default 15)",
    )
    parser.add_argument("--seed", type=int, default=1234, help="deterministic RNG seed")
    parser.add_argument(
        "--keep", action="store_true", help="keep the temp collection dir"
    )
    args = parser.parse_args()

    if args.cards < 1:
        parser.error("--cards must be >= 1")
    if args.cards > MAX_CARDS:
        parser.error(f"--cards must be <= {MAX_CARDS}")

    tmpdir = tempfile.mkdtemp(prefix="pgrep_bench_")
    path = f"{tmpdir}/bench.anki2"

    print("pgrep engine benchmark")
    print(f"  building {args.cards} cards (seed {args.seed}) ...", flush=True)
    build_start = time.perf_counter()
    bench = Bench(path, args.cards, args.seed)
    build_secs = time.perf_counter() - build_start

    info = bench.info
    demo = info["demo"] or {}
    bs = info["build_seconds"]
    print(
        f"  built in {build_secs:.2f}s "
        f"(add_notes {bs['add_notes']:.2f}s, fsrs {bs['fsrs_state']:.2f}s, "
        f"demo {bs['inject_demo']:.2f}s)"
    )
    print(
        f"  collection: {info['card_count']} cards, {info['note_count']} notes, "
        f"deck {info['deck']}"
    )
    print(
        f"  demo attempts injected: {demo.get('attempts_created', 0)} "
        f"across {len(demo.get('covered_categories', []))} categories; "
        f"scheduler: {type(bench.col.sched).__name__}"
    )
    # Sanity: report whether the scores actually light up (honest context).
    r = cast(dict, bench.readiness_score())
    m = cast(dict, bench.memory_score())
    print(
        f"  scores live? memory abstain={m['overall']['abstain']}, "
        f"readiness abstain={r['abstain']} "
        f"(scaled={r.get('scaled')}, coverage={r['coverage_pct']:.0%})"
    )
    print(f"  iters={args.iters}, reopens={args.reopens}\n")

    results: dict[str, list[float]] = {}
    results["next_card"] = measure(bench.next_card, args.iters)
    results["memory_score"] = measure(bench.memory_score, args.iters)
    results["performance_score"] = measure(bench.performance_score, args.iters)
    results["readiness_score"] = measure(bench.readiness_score, args.iters)
    results["coverage"] = measure(bench.coverage, args.iters)
    results["dashboard_refresh"] = measure(bench.dashboard, args.iters)
    # Cold first-load reopen loop (measured before the answer loop mutates state).
    results["dashboard_first_load"] = bench.measure_first_load(args.reopens)
    # Answering consumes due cards, so do it last.
    results["answer_card"] = bench.measure_answers(args.iters)

    header = f"{'action':<22}{'p50 (ms)':>11}{'p95 (ms)':>11}{'worst (ms)':>12}{'n':>7}"
    print(header)
    print("-" * len(header))
    for name in (
        "next_card",
        "answer_card",
        "memory_score",
        "performance_score",
        "readiness_score",
        "coverage",
        "dashboard_refresh",
        "dashboard_first_load",
    ):
        print(format_row(name, results[name]))

    print(
        f"\nDeck size: {info['card_count']} cards ({args.cards} synthetic pgrep cards)"
    )
    print("Spec targets (section 7h / 10):")

    next_p95 = percentile(results["next_card"], 95)
    load_p95 = percentile(results["dashboard_first_load"], 95)
    refresh_p95 = percentile(results["dashboard_refresh"], 95)

    checks = [
        ("next-card p95", next_p95, TARGET_NEXT_CARD_MS),
        ("dashboard first-load p95", load_p95, TARGET_FIRST_LOAD_MS),
        ("dashboard refresh p95", refresh_p95, TARGET_REFRESH_MS),
    ]
    passed = 0
    for label, value, threshold in checks:
        line = target_line(label, value, threshold)
        if "[PASS]" in line:
            passed += 1
        print(line)

    all_pass = passed == len(checks)
    verdict = "PASS" if all_pass else "FAIL"
    print(
        f"\nRESULT: {verdict} ({passed}/{len(checks)} measurable targets met) "
        f"at {args.cards} cards"
    )

    if args.keep:
        print(f"\n(kept collection at {path})")
    else:
        import shutil

        bench.col.close()
        shutil.rmtree(tmpdir, ignore_errors=True)

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
