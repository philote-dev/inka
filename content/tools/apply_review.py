"""Apply Frank's review verdicts from the disposable review sheet.

Reads content/gold/REVIEW-SHEET-reviewed.md, then for each problem:
  - DROP     -> move the file to content/gold/dropped/ and log the reason
  - FIX-KEY  -> record the new key on the item (rationale swap done separately)
  - KEEP     -> mark verified

Every kept item gets verification.status = "verified", verified_by Frank, the
date, and Frank's note if he left one. Cards are left untouched (reviewed
separately). Writes content/gold/dropped/DROP-LOG.md so the drop reasons survive
after the sheet is deleted.

Run:
    python content/tools/apply_review.py
"""

from __future__ import annotations

import json
import os
import re
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.dirname(HERE)
PROBLEMS = os.path.join(CONTENT, "gold", "problems")
DROPPED = os.path.join(CONTENT, "gold", "dropped")
SHEET = os.path.join(CONTENT, "gold", "REVIEW-SHEET-reviewed.md")
TODAY = "2026-07-05"


def parse_sheet() -> dict[str, dict]:
    txt = open(SHEET, encoding="utf-8").read()
    out: dict[str, dict] = {}
    for b in re.split(r"^### \d+\. `", txt, flags=re.M)[1:]:
        iid = re.match(r"([^`]+)`", b).group(1)
        vm = re.search(r"DROP\)\s*:\s*(.*?)\s*-?\s*Notes\s*:", b, flags=re.S)
        verdict = (vm.group(1).strip() if vm else "")
        nm = re.search(r"Notes\s*:\s*(.*?)(?:\n---|\Z)", b, flags=re.S)
        note = (nm.group(1).strip() if nm else "")
        if note in ("---", "-"):
            note = ""
        out[iid] = {"verdict": verdict, "note": note}
    return out


def mark_verified(item: dict, note: str, extra: str = "") -> None:
    v = item.setdefault("verification", {})
    v["status"] = "verified"
    v["verified_by"] = "Frank"
    v["verified_at"] = TODAY
    if note:
        v["frank_note"] = note
    if extra:
        v["adjudication"] = extra


def main() -> None:
    verdicts = parse_sheet()
    os.makedirs(DROPPED, exist_ok=True)

    kept = fixed = dropped = 0
    drop_log = ["# Dropped gold problems (Frank review, 2026-07-05)", "",
                "These items were cut during the human audit. Kept here for the record.", ""]
    fix_log = []

    for name in sorted(os.listdir(PROBLEMS)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(PROBLEMS, name)
        item = json.load(open(path, encoding="utf-8"))
        iid = item["id"]
        rec = verdicts.get(iid, {"verdict": "KEEP", "note": ""})
        verdict, note = rec["verdict"], rec["note"]
        up = verdict.upper()

        if up.startswith("DROP"):
            shutil.move(path, os.path.join(DROPPED, name))
            drop_log.append(f"- `{iid}` ({item.get('blueprint_area','')}): {note or 'no reason given'}")
            dropped += 1
        elif up.startswith("FIX-KEY"):
            newkey = up.split(":", 1)[1].strip()[:1]
            fix_log.append((iid, item["key"], newkey, note))
            mark_verified(item, note, extra=f"Key corrected to {newkey} by Frank. {note}")
            item["_pending_key_fix"] = newkey  # hand-applied next
            json.dump(item, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            fixed += 1
        else:
            mark_verified(item, note)
            json.dump(item, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            kept += 1

    open(os.path.join(DROPPED, "DROP-LOG.md"), "w", encoding="utf-8").write("\n".join(drop_log) + "\n")

    print(f"kept+verified: {kept}   fix-key: {fixed}   dropped: {dropped}")
    print(f"remaining problem gold: {kept + fixed}")
    if fix_log:
        print("key fixes (apply rationale swap by hand):")
        for iid, old, new, note in fix_log:
            print(f"  {iid}: {old} -> {new}")


if __name__ == "__main__":
    main()
