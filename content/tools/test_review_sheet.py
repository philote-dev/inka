"""Offline tests for the shared review-sheet module (build/parse/manifest).

Runnable both as ``python3 -m pytest content/tools/test_review_sheet.py`` and as
``python3 content/tools/test_review_sheet.py`` (the __main__ block runs the same
checks without pytest).
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import review_sheet as rs  # noqa: E402

HEADER = [
    "# Sample review (disposable)",
    "",
    "Fill each `-> your call:` line, then tell me it is ready.",
    "",
    "---",
    "",
]


def _items():
    return [
        {"id": "p4-prob-0001", "rec": "KEEP", "note": "blind solve already agrees"},
        {"id": "p4-prob-0042", "rec": "REVIEW", "note": "needs a human look"},
        {"id": "p4-prob-0283", "rec": "REDRAW", "note": "convention issue"},
    ]


def _recommend(it):
    return it["rec"]


def _id_of(it):
    return it["id"]


def _block(it):
    """A block in the shared shape: '### <id>', a recommendation, body, verdict slot."""
    return "\n".join([
        f"### {it['id']}  [{it['rec']}]",
        f"recommendation: {_recommend(it)}",
        "",
        f"**Note.** {it['note']}",
        "",
        f"-> your call: {_recommend(it)}",
        "", "---", "",
    ])


def test_build_matches_manual_assembly():
    """build() reproduces the make_* scripts' header + joined blocks byte for byte."""
    items = _items()
    md = rs.build(items, header=HEADER, recommend=_recommend, block=_block, id_of=_id_of)
    expected = "\n".join(HEADER) + "\n" + "\n".join(_block(it) for it in items)
    assert md == expected
    assert md.startswith("# Sample review (disposable)\n")


def test_build_wires_block_and_recommend():
    """build() calls the stage's block once per item, in order, dropping nothing."""
    seen = []

    def spy_block(it):
        seen.append(it["id"])
        return _block(it)

    items = _items()
    md = rs.build(items, header=HEADER, recommend=_recommend, block=spy_block, id_of=_id_of)
    assert seen == [it["id"] for it in items]
    for it in items:
        assert f"### {it['id']}" in md
        assert f"-> your call: {it['rec']}" in md


def test_parse_roundtrips_build():
    """A freshly built sheet parses back to the recommendation pre-filled in each slot."""
    items = _items()
    md = rs.build(items, header=HEADER, recommend=_recommend, block=_block, id_of=_id_of)
    got = rs.parse(md, rs.PROBLEM_ID_RE)
    assert got == {
        "p4-prob-0001": "KEEP",
        "p4-prob-0042": "REVIEW",
        "p4-prob-0283": "REDRAW",
    }
    # build pre-fills each slot with recommend(it), so the round trip equals the manifest.
    assert got == rs.manifest(items, recommend=_recommend, id_of=_id_of)


def test_roundtrip_includes_default_for_blank_slot():
    """Build a sheet whose last block leaves the slot blank: it parses to the default."""
    items = _items()

    def block_maybe_blank(it):
        if it["id"] == "p4-prob-0283":  # a reviewer who left the slot empty
            return "\n".join([
                f"### {it['id']}",
                "recommendation: REDRAW",
                "",
                f"**Note.** {it['note']}",
                "",
                "-> your call:",
            ])
        return _block(it)

    md = rs.build(items, header=HEADER, recommend=_recommend, block=block_maybe_blank,
                  id_of=_id_of)
    got = rs.parse(md, rs.PROBLEM_ID_RE)
    assert got["p4-prob-0001"] == "KEEP"
    assert got["p4-prob-0042"] == "REVIEW"
    assert got["p4-prob-0283"] == "KEEP"  # blank slot falls back to the stage default


def test_parse_preserves_edited_verdicts():
    """Verdicts a reviewer edits in, including a REDRAW note, survive parse verbatim."""
    items = _items()
    md = rs.build(items, header=HEADER, recommend=_recommend, block=_block, id_of=_id_of)
    md = md.replace("-> your call: KEEP", "-> your call: DROP")
    md = md.replace("-> your call: REDRAW",
                    "-> your call: REDRAW: swap the inner and outer radius labels")
    got = rs.parse(md, rs.PROBLEM_ID_RE)
    assert got["p4-prob-0001"] == "DROP"
    assert got["p4-prob-0042"] == "REVIEW"
    assert got["p4-prob-0283"] == "REDRAW: swap the inner and outer radius labels"


def test_parse_default_when_value_absent():
    """An absent '-> your call:' line uses the default; a custom default is honored."""
    md = (
        "### p4-prob-0001\n-> your call: DROP\n\n---\n\n"
        "### p4-prob-0007\nrecommendation: KEEP\n\n**Note.** slot deleted\n\n---\n"
    )
    assert rs.parse(md, rs.PROBLEM_ID_RE) == {"p4-prob-0001": "DROP", "p4-prob-0007": "KEEP"}
    assert rs.parse(md, rs.PROBLEM_ID_RE, default="REVIEW")["p4-prob-0007"] == "REVIEW"


def test_parse_ignores_non_id_blocks():
    """The header and any non-id block are skipped, only real ids are collected."""
    md = (
        "# Problem review (disposable)\n\nsome preamble\n\n---\n\n"
        "### p4-prob-0001\n-> your call: KEEP\n\n---\n"
    )
    assert rs.parse(md, rs.PROBLEM_ID_RE) == {"p4-prob-0001": "KEEP"}


def test_id_regex_matches_each_stage_heading():
    """PROBLEM_ID_RE captures the id at the start of every stage's block heading."""
    headings = {
        "p4-prob-0001": "p4-prob-0001  (Mechanics / kinematics, quantitative)",  # pool
        "p4-prob-0283": "p4-prob-0283",  # figure
        "p4-prob-0042": "p4-prob-0042  [high]",  # giveaway
    }
    for pid, heading in headings.items():
        m = re.match(rs.PROBLEM_ID_RE, heading)
        assert m is not None
        assert m.group(1) == pid
    assert re.match(rs.PROBLEM_ID_RE, "Problem review (disposable)") is None
    assert re.match(rs.PROBLEM_ID_RE, "prob-0001") is None


def test_manifest_wires_recommend_and_id_of():
    """manifest() maps id_of -> recommend for every item, preserving item order."""
    items = _items()
    man = rs.manifest(items, recommend=_recommend, id_of=_id_of)
    assert man == {
        "p4-prob-0001": "KEEP",
        "p4-prob-0042": "REVIEW",
        "p4-prob-0283": "REDRAW",
    }
    assert list(man) == ["p4-prob-0001", "p4-prob-0042", "p4-prob-0283"]


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
