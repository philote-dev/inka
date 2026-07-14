"""Offline tests for the foundry escalation review sheet.

Runnable as ``python3 -m pytest content/tools/test_foundry_escalation.py`` or
``python3 content/tools/test_foundry_escalation.py``.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import make_foundry_escalation as me  # noqa: E402
import review_sheet  # noqa: E402


def test_escalation_sheet_roundtrip():
    items = [{
        "id": "p4-prob-9001",
        "reason": "key: low confidence",
        "stem": "A mass slides...",
        "panel": {"decision": "escalate"},
    }]
    md = me.render_escalation_sheet(items)
    assert review_sheet.parse(md, review_sheet.PROBLEM_ID_RE, default="ESCALATE")[
        "p4-prob-9001"
    ] == "ESCALATE"


def test_block_uses_recommend():
    it = {
        "id": "p4-prob-9001",
        "reason": "key: low confidence",
        "stem": "A mass slides down a frictionless incline.",
    }
    text = me.block(it)
    assert text.startswith("### p4-prob-9001\n")
    assert "reason: key: low confidence" in text
    assert "stem: A mass slides down a frictionless incline." in text
    assert "-> your call: ESCALATE" in text
    assert text.endswith("---\n")


def test_render_includes_header_and_all_items():
    items = [
        {"id": "p4-prob-9001", "reason": "a", "stem": "one"},
        {"id": "p4-prob-9002", "reason": "b", "stem": "two"},
    ]
    md = me.render_escalation_sheet(items)
    assert md.startswith("# Foundry escalation\n")
    assert "### p4-prob-9001" in md
    assert "### p4-prob-9002" in md


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
