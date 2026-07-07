"""Turn the technique-giveaway verdicts into a disposable review file.

One block per flagged problem: the id, severity, what the stem hands over, the
judge's suggested fix, the stem, and a `-> your call:` slot. Default
recommendation: FIX for high severity (reword so the relation is not given),
REVIEW for low. Tokens the applier understands: FIX (auto-reword via the model),
KEEP (leave as-is), DROP (remove the problem).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import review_sheet  # noqa: E402


def rec(v: dict) -> str:
    return "FIX" if v.get("severity") == "high" else "REVIEW"


def block(v: dict) -> str:
    return "\n".join([
        f"### {v['id']}  [{v.get('severity','?')}]",
        f"recommendation: {rec(v)}",
        "",
        f"- hands over: {v.get('what','')}",
        f"- suggested fix: {v.get('fix','')}",
        "",
        f"**Stem.** {v.get('stem','')}",
        "",
        f"-> your call: {rec(v)}",
        "", "---", "",
    ])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verdicts", default="content/run/triple/technique_giveaway.json")
    ap.add_argument("--out", default="content/run/review")
    args = ap.parse_args()

    data = json.load(open(args.verdicts, encoding="utf-8"))
    flagged = [v for v in data["verdicts"] if v.get("gives_away")]
    flagged.sort(key=lambda v: (v.get("severity") != "high", v["id"]))
    high = sum(1 for v in flagged if v.get("severity") == "high")

    os.makedirs(args.out, exist_ok=True)
    head = [
        "# Technique-giveaway review (disposable)",
        "",
        f"A judge pass over all {data['n']} problems found **{len(flagged)}** whose "
        f"stem hands the solver the governing relation or method ({high} high "
        "severity, the rest borderline).",
        "",
        "Fill each `-> your call:` line. Tokens: `FIX` (I reword the stem to remove "
        "the given relation, keeping all numbers and the answer the same), `KEEP` "
        "(it is fine as written), `DROP` (remove the problem). Add a note after FIX "
        "to steer it.",
        "",
        "Reply 'accept giveaway fixes' to apply the defaults (FIX the high ones, "
        "you decide the borderline).",
        "",
        "---",
        "",
    ]
    with open(os.path.join(args.out, "03-giveaway.md"), "w", encoding="utf-8") as fh:
        fh.write(review_sheet.build(flagged, header=head, recommend=rec, block=block,
                                    id_of=lambda v: v["id"]))
    json.dump(review_sheet.manifest(flagged, recommend=rec, id_of=lambda v: v["id"]),
              open(os.path.join(args.out, "03-giveaway.manifest.json"), "w",
                   encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"flagged {len(flagged)} (high {high}); wrote 03-giveaway.md")


if __name__ == "__main__":
    main()
