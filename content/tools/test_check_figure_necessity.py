"""Offline tests for the figure necessity/reference checker."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check_figure_necessity as c  # noqa: E402

_SVG = '<svg viewBox="0 0 10 10" stroke="currentColor"></svg>'


def _problems():
    return [
        {"id": "ok_fig", "figure_required": True, "stem": f"A lens setup. {_SVG}"},
        {"id": "miss_req", "figure_required": True, "stem": "A lens with focal length f."},
        {"id": "dangling", "figure_required": False,
         "stem": "As shown in the figure, a ray hits the mirror."},
        {"id": "ok_text", "figure_required": False,
         "stem": "A photon of energy E scatters off a free electron. Find the shift."},
        {"id": "text_has_fig", "figure_required": False, "stem": f"Text only. {_SVG}"},
    ]


def test_dangling_detected():
    rep = c.check(_problems())
    assert {d["id"] for d in rep["dangling_refs"]} == {"dangling"}


def test_missing_required_detected():
    rep = c.check(_problems())
    assert {d["id"] for d in rep["figure_required_missing"]} == {"miss_req"}


def test_textonly_with_figure_detected():
    rep = c.check(_problems())
    assert {d["id"] for d in rep["textonly_with_figure"]} == {"text_has_fig"}


def test_clean_case_has_no_failures():
    clean = [
        {"id": "a", "figure_required": True, "stem": f"Circuit shown. {_SVG}"},
        {"id": "b", "figure_required": False, "stem": "A self-contained kinematics problem."},
    ]
    rep = c.check(clean)
    assert c.failures(rep) == []


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
