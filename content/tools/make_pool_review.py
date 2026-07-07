"""Build the disposable problem review file for the flagged grow candidates.

Refused/malformed items are auto-dropped (listed for the record, no action). The
rest (CAS-unverified, key-unconfirmed, low-confidence) get a block with the stem,
choices (key marked), the independent blind solve, the CAS expression, and the
source, ending in a machine-parseable ``-> your call:`` slot. A recommendation is
pre-filled: KEEP when the blind solve already agrees with the key (a CAS gap on a
confirmed answer), otherwise REVIEW.

Writes content/run/review/01-problems.md and 01-problems.manifest.json. The
applier (apply_pool_review.py) reads the filled slots, applies them, and the file
is deleted.
"""

from __future__ import annotations

import argparse
import json
import os

LETTERS = "ABCDE"


def is_refused(it: dict) -> bool:
    return bool(it.get("refused")) or any(
        f.startswith("refused") for f in it.get("flags", [])
    )


def recommend(it: dict) -> str:
    if it.get("key_self_consistent") is True:
        return "KEEP"
    if it.get("key_self_consistent") is False:
        return "FIX-KEY or DROP"
    return "REVIEW"


def block(it: dict) -> str:
    pid = it["id"]
    lines = [
        f"### {pid}  ({it.get('blueprint_area')} / {it.get('finest_unit','')}, "
        f"{it.get('problem_kind','')})",
        f"flags: {', '.join(it.get('flags', [])) or 'none'}",
        f"recommendation: {recommend(it)}",
        "",
        f"**Stem.** {it.get('stem','')}",
        "",
    ]
    key = str(it.get("key", "")).strip().upper()
    for i, ch in enumerate(it.get("choices", [])):
        mark = "  <- key" if i < len(LETTERS) and LETTERS[i] == key else ""
        lines.append(f"- {ch}{mark}")
    lines.append("")
    solve = it.get("independent_solve")
    if solve:
        agree = "agrees" if solve == key else "DISAGREES"
        lines.append(f"_blind solve: {solve} ({agree} with key {key})_")
    comp = it.get("computational")
    if isinstance(comp, dict) and comp.get("expression"):
        lines.append(
            f"_CAS: `{comp.get('expression')}` = {comp.get('expected')} "
            f"(verified={it.get('cas_verified')})_"
        )
    lines.append(f"_source: {it.get('source_ref') or '(none)'}_")
    lines += ["", f"-> your call: {recommend(it)}", "", "---", ""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--flagged", default="content/run/triple/pool/merged/flagged.json")
    ap.add_argument("--out", default="content/run/review")
    args = ap.parse_args()

    flagged = json.load(open(args.flagged, encoding="utf-8"))
    refused = [it for it in flagged if is_refused(it)]
    review = [it for it in flagged if not is_refused(it)]
    review.sort(key=lambda z: (z.get("blueprint_area", ""), z.get("id", "")))

    os.makedirs(args.out, exist_ok=True)
    head = [
        "# Problem review (disposable)",
        "",
        "Fill each `-> your call:` line, then tell me it is ready. I apply the "
        "verdicts and delete this file. Tokens: `KEEP`, `DROP`, or `FIX: <note>`.",
        "For a wrong key use `FIX-KEY: X`.",
        "",
        f"- **{len(review)} to review** below (CAS-unverified or key-unconfirmed). "
        "Most are likely fine; the recommendation is pre-filled.",
        f"- **{len(refused)} auto-dropped** (malformed or the model declined): "
        + ", ".join(sorted(it["id"] for it in refused)) + ".",
        "",
        "The recommendation defaults are set. If you agree with all of them, just "
        "reply 'accept recommendations' and I will apply them.",
        "",
        "---",
        "",
    ]
    body = [block(it) for it in review]
    md = "\n".join(head) + "\n" + "\n".join(body)
    with open(os.path.join(args.out, "01-problems.md"), "w", encoding="utf-8") as fh:
        fh.write(md)

    manifest = {
        "auto_dropped": sorted(it["id"] for it in refused),
        "review": {it["id"]: recommend(it) for it in review},
    }
    json.dump(manifest, open(os.path.join(args.out, "01-problems.manifest.json"), "w",
                             encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"review: {len(review)}  auto-dropped: {len(refused)}")
    print(f"wrote {os.path.join(args.out, '01-problems.md')}")


if __name__ == "__main__":
    main()
