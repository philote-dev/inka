"""Apply the verdicts from the reviewed problem file into an accepted set.

Parses each ``-> your call:`` line: KEEP accepts the problem, DROP removes it,
FIX-KEY: X overrides the answer key, FIX: <note> keeps it and records the note
for a manual pass. Kept items are normalized to the shipped bundle shape (via
merge_pool.to_bundle_problem) and written to --out. Also emits an applied log so
the decisions survive after the disposable review file is deleted.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import merge_pool  # noqa: E402


def parse_verdicts(md: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for b in re.split(r"\n### ", "\n" + md):
        m = re.match(r"(p4-prob-\d+)", b)
        if not m:
            continue
        cm = re.search(r"-> your call:\s*(.+)", b)
        out[m.group(1)] = cm.group(1).strip() if cm else "KEEP"
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reviewed", default="content/run/review/01-problems-reviewed.md")
    ap.add_argument("--flagged", default="content/run/triple/pool/merged/flagged.json")
    ap.add_argument("--out", default="content/run/triple/pool/merged/accepted_from_review.json")
    ap.add_argument("--log", default="content/run/triple/pool/merged/review_applied.json")
    args = ap.parse_args()

    verdicts = parse_verdicts(open(args.reviewed, encoding="utf-8").read())
    flagged = {it["id"]: it for it in json.load(open(args.flagged, encoding="utf-8"))}

    kept: list[dict] = []
    dropped: list[str] = []
    fixes: list[dict] = []
    keyfixes: list[dict] = []
    for pid, v in verdicts.items():
        it = flagged.get(pid)
        if it is None:
            continue
        u = v.upper()
        if u.startswith("DROP"):
            dropped.append(pid)
            continue
        if u.startswith("FIX-KEY"):
            mk = re.search(r"FIX-KEY:?\s*([A-E])", u)
            if mk:
                it = dict(it)
                it["key"] = mk.group(1)
                keyfixes.append({"id": pid, "new_key": mk.group(1)})
            kept.append(it)
            continue
        if u.startswith("FIX"):
            fixes.append({"id": pid, "note": v})
            kept.append(it)
            continue
        kept.append(it)  # KEEP

    accepted = [merge_pool.to_bundle_problem(it) for it in kept]
    json.dump(accepted, open(args.out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    log = {
        "kept": [it["id"] for it in kept],
        "dropped": dropped,
        "key_fixes": keyfixes,
        "fix_notes": fixes,
        "figure_required_kept": sum(1 for it in kept if it.get("figure_required")),
    }
    json.dump(log, open(args.log, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"kept {len(kept)}, dropped {len(dropped)}, key-fixes {len(keyfixes)}, "
          f"fix-notes {len(fixes)}, figure_required among kept "
          f"{log['figure_required_kept']}")
    if fixes:
        print("manual FIX notes:")
        for f in fixes:
            print(f"  {f['id']}: {f['note']}")
    print(f"wrote {args.out} and {args.log}")


if __name__ == "__main__":
    main()
