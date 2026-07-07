"""Offline tests for grow mode and the figure policy (no API, no corpus)."""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import generate_content_set as g  # noqa: E402


def _probs(area: str, n: int, start: int = 0) -> list[dict]:
    return [
        {"kind": "problem", "category": area, "id": f"p4-prob-{start + i:04d}"}
        for i in range(n)
    ]


def test_figure_share_optics():
    ts = _probs("optics_waves", 10)
    g.assign_figure_required(ts)
    assert sum(t["figure_required"] for t in ts) == round(0.55 * 10)


def test_figure_share_relativity_low():
    ts = _probs("special_relativity", 10)
    g.assign_figure_required(ts)
    assert sum(t["figure_required"] for t in ts) == round(0.10 * 10)


def test_figure_share_is_area_local():
    ts = _probs("optics_waves", 4) + _probs("quantum", 4, start=100)
    g.assign_figure_required(ts)
    opt = [t for t in ts if t["category"] == "optics_waves"]
    qm = [t for t in ts if t["category"] == "quantum"]
    assert sum(t["figure_required"] for t in opt) == round(0.55 * 4)
    assert sum(t["figure_required"] for t in qm) == round(0.15 * 4)


def test_build_grow_targets_sums_and_ids():
    bp = json.load(open(g.BLUEPRINT, encoding="utf-8"))
    ts, seq = g.build_grow_targets(bp, 275, 200)
    assert len(ts) == 275
    assert all(t["kind"] == "problem" for t in ts)
    ids = [t["id"] for t in ts]
    assert len(set(ids)) == 275
    nums = [int(i.split("-")[-1]) for i in ids]
    assert min(nums) == 201
    assert seq == 200 + 275


def test_dedup_drops_bundle_clone():
    # Avoid the heavy reject-memorized path; we only test the seen-preload drop.
    class _R:
        dropped: list = []

        def as_dict(self):
            return {}

    g.splits.reject_memorized = lambda items: _R()  # type: ignore[assignment]
    stem = "A block slides down a frictionless incline of angle theta."
    items = [
        {"id": "x1", "stem": stem, "refused": False},
        {"id": "x2", "stem": "A completely different quantum well question.", "refused": False},
    ]
    seen = {g.verify.normalized_front_hash(stem)}
    final, dropped, _memo, _rep = g.dedup_and_firewall(items, seen)
    kept = {it["id"] for it in final}
    assert "x1" not in kept
    assert "x2" in kept
    assert any(d["id"] == "x1" for d in dropped)


if __name__ == "__main__":
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
