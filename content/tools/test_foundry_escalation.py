"""Offline tests for the foundry escalation review sheet.

Runnable as ``python3 -m pytest content/tools/test_foundry_escalation.py`` or
``python3 content/tools/test_foundry_escalation.py``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import foundry  # noqa: E402
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


def test_foundry_caps_requested_n_by_verifier_accuracy():
    assert foundry._effective_n(8, 0.8) == 6
    assert foundry._effective_n(3, 0.8) == 3


def test_foundry_writes_partition_files_for_escalation_cli(tmp_path: Path):
    result = foundry.foundry_loop.SlotResult(
        accepted=[{"id": "a"}],
        rejected=[{"id": "r"}],
        escalated=[{"id": "e"}],
    )
    run_dir = foundry._write_result(str(tmp_path), "run-1", result)

    assert run_dir == tmp_path / "run-1"
    assert json.loads((run_dir / "accepted.json").read_text()) == [{"id": "a"}]
    assert json.loads((run_dir / "rejected.json").read_text()) == [{"id": "r"}]
    assert json.loads((run_dir / "escalated.json").read_text()) == [{"id": "e"}]
    summary = json.loads((run_dir / "summary.json").read_text())
    assert summary["yield_rate"] == 1 / 3


if __name__ == "__main__":
    import tempfile
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            # Pytest fixture params are only available under pytest; for the
            # plain-python harness, inject a temporary directory when needed.
            if fn.__code__.co_argcount == 1 and fn.__code__.co_varnames[0] == "tmp_path":
                with tempfile.TemporaryDirectory() as td:
                    fn(Path(td))
            else:
                fn()
            print(f"PASS {fn.__name__}")
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
