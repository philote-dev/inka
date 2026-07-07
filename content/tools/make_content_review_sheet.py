"""Build Frank's review sheet for the P4 default content set.

Frank does not hand-review all ~490 generated items. This splits them into two
buckets, per the P4 phase-1 brief:

  A. MUST-REVIEW  = every item the pipeline flagged: refused, low-confidence
     needs_review, CAS-failed, key-unconfirmed, or reject-memorized. Grouped by
     reason so the eye goes where the machine was unsure.
  B. SPOT-CHECK   = a random, area-stratified sample (default 12%) of the clean,
     high-confidence items, to sanity-check the quality of what passed.

Reads content/run/p4/content_set.json (+ rejected_memorized.json, exam_form.json)
and writes:
  - content/run/p4/REVIEW-SHEET.md      the human sheet (verdict lines to fill)
  - content/run/p4/review_manifest.json which ids are in which bucket

Private, git-ignored. Run:
    python content/tools/make_content_review_sheet.py --spot-pct 12
"""

from __future__ import annotations

import argparse
import json
import os
import random
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.dirname(HERE)
DEFAULT_DIR = os.path.join(CONTENT, "run", "p4")

# Human-readable flag headings, in review priority order.
REASON_ORDER = [
    ("refused", "Refused (cite-or-refuse, giveaway leak, malformed, or CAS-refused)"),
    ("cas_failed", "CAS check failed (computational answer not verified by SymPy)"),
    ("key_unconfirmed", "Key not confirmed by an independent re-solve"),
    ("needs_review", "Low generated confidence (below 0.60)"),
    ("reject-memorized", "Too close to an ETS/fed example (firewall reject)"),
]


def _reason_key(item: dict) -> str:
    dr = item.get("dropped_reason", "")
    if dr.startswith("reject-memorized"):
        return "reject-memorized"
    for key, _ in REASON_ORDER:
        if key == "reject-memorized":
            continue
        if any(f.split(":", 1)[0] == key for f in item.get("flags", [])):
            return key
    return "needs_review"


def card_block(n: int, c: dict, show_flag: bool) -> str:
    L = [f"#### {n}. `{c['id']}`  —  {c['blueprint_area']} / {c.get('finest_unit','')}  "
         f"—  {c.get('card_kind','')}  —  conf {c.get('confidence',0):.2f}", ""]
    if show_flag and c.get("flags"):
        L.append(f"> FLAG: {'; '.join(c['flags'])}")
        L.append("")
    L.append(f"- **tag:** `{c.get('blueprint_tag','')}`")
    L.append(f"- **source:** {c.get('source_ref') or '(none — refused)'}")
    L.append("")
    L.append(f"**Front.** {c.get('front','')}")
    L.append("")
    L.append(f"**Back.** {c.get('back','')}")
    comp = c.get("computational")
    if isinstance(comp, dict) and comp.get("expression"):
        L.append("")
        L.append(f"_CAS: `{comp.get('expression')}` = {comp.get('expected')} "
                 f"(verified={c.get('cas_verified')})_")
    L += ["", "- Verdict (KEEP / FIX / DROP): ", "- Notes: ", "", "---", ""]
    return "\n".join(L)


def problem_block(n: int, p: dict, show_flag: bool) -> str:
    L = [f"#### {n}. `{p['id']}`  —  {p['blueprint_area']} / {p.get('finest_unit','')}  "
         f"—  {p.get('problem_kind','')}  —  conf {p.get('confidence',0):.2f}", ""]
    if show_flag and p.get("flags"):
        L.append(f"> FLAG: {'; '.join(p['flags'])}")
        L.append("")
    L.append(f"- **tag:** `{p.get('blueprint_tag','')}`")
    L.append(f"- **source:** {p.get('source_ref') or '(none — refused)'}")
    if p.get("independent_solve"):
        L.append(f"- **key self-consistency:** generated key {p.get('key')}, "
                 f"independent solve {p.get('independent_solve')} "
                 f"(consistent={p.get('key_self_consistent')})")
    L.append("")
    L.append(f"**Stem.** {p.get('stem','')}")
    L.append("")
    for i, ch in enumerate(p.get("choices", [])):
        lab = "ABCDE"[i] if i < 5 else str(i)
        mark = "  **← key**" if lab == p.get("key") else ""
        L.append(f"- {ch}{mark}")
    L.append("")
    rats = p.get("distractor_rationales") or {}
    tags = {d.get("label"): d.get("misconception_tag") for d in p.get("distractors", [])
            if isinstance(d, dict)}
    if rats:
        L.append("_Distractor rationales:_")
        for lab in sorted(rats):
            L.append(f"  - **{lab}** [{tags.get(lab,'')}]: {rats[lab]}")
        L.append("")
    if p.get("solution_decomposition"):
        L.append("_Solution decomposition (ladder):_")
        for s in p["solution_decomposition"]:
            if isinstance(s, dict):
                L.append(f"  - {s.get('subgoal','')} — {s.get('rubric','')}")
        L.append("")
    comp = p.get("computational")
    if isinstance(comp, dict) and comp.get("expression"):
        L.append(f"_CAS: `{comp.get('expression')}` = {comp.get('expected')} "
                 f"(verified={p.get('cas_verified')})_")
        L.append("")
    L += [f"Generated key: **{p.get('key','')}**", "",
          "- Verdict (KEEP / FIX-KEY:X / DROP): ", "- Notes: ", "", "---", ""]
    return "\n".join(L)


def render_bucket(items: list[dict], show_flag: bool) -> tuple[list[str], int]:
    cards = [x for x in items if x["kind"] == "card"]
    probs = [x for x in items if x["kind"] == "problem"]
    out, n = [], 0
    if cards:
        out.append(f"### Cards ({len(cards)})\n")
        for c in cards:
            n += 1
            out.append(card_block(n, c, show_flag))
    if probs:
        out.append(f"### Problems ({len(probs)})\n")
        for p in probs:
            n += 1
            out.append(problem_block(n, p, show_flag))
    return out, n


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the P4 content review sheet.")
    ap.add_argument("--dir", default=DEFAULT_DIR)
    ap.add_argument("--spot-pct", type=float, default=12.0)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    items = json.load(open(os.path.join(args.dir, "content_set.json"), encoding="utf-8"))
    memo_path = os.path.join(args.dir, "rejected_memorized.json")
    memorized = json.load(open(memo_path, encoding="utf-8")) if os.path.exists(memo_path) else []
    exam_path = os.path.join(args.dir, "exam_form.json")
    exam = json.load(open(exam_path, encoding="utf-8")) if os.path.exists(exam_path) else {"item_ids": []}
    exam_ids = set(exam.get("item_ids", []))

    flagged = [x for x in items if x["status"] == "flagged"] + memorized
    clean = [x for x in items if x["status"] == "clean"]

    # MUST-REVIEW, grouped by reason.
    by_reason: dict[str, list[dict]] = defaultdict(list)
    for x in flagged:
        by_reason[_reason_key(x)].append(x)

    # SPOT-CHECK: area-stratified sample of the clean items.
    rng = random.Random(args.seed)
    by_area_kind: dict[tuple, list[dict]] = defaultdict(list)
    for x in clean:
        by_area_kind[(x["blueprint_area"], x["kind"])].append(x)
    spot: list[dict] = []
    for key, group in by_area_kind.items():
        group_sorted = sorted(group, key=lambda z: z["id"])
        rng.shuffle(group_sorted)
        k = max(1, round(len(group_sorted) * args.spot_pct / 100.0))
        spot.extend(group_sorted[:k])
    spot_ids = {x["id"] for x in spot}
    # Always include a couple of exam-form items in the spot-check for extra eyes.
    for x in clean:
        if len(spot_ids) and x["id"] in exam_ids and x["id"] not in spot_ids and rng.random() < 0.15:
            spot.append(x)
            spot_ids.add(x["id"])
    spot.sort(key=lambda z: (z["blueprint_area"], z["kind"], z["id"]))

    head = [
        "# P4 content-set review sheet (disposable, phase 1)",
        "",
        "DELETE after review. Private, never committed. Generated by",
        "`content/tools/make_content_review_sheet.py` from `content_set.json`.",
        "",
        "Nothing here is landed in the app yet. Fill each **Verdict** line; the",
        "landing phase applies your verdicts.",
        "",
        "## Two buckets",
        "",
        f"- **A. MUST-REVIEW ({len(flagged)})** — every item the pipeline flagged. "
        "Please review all of these.",
        f"- **B. SPOT-CHECK ({len(spot)})** — a random ~"
        f"{args.spot_pct:.0f}% area-stratified sample of the {len(clean)} clean, "
        "high-confidence items. Skim to confirm quality.",
        "",
        "Verdicts: cards `KEEP` / `FIX` (say what) / `DROP`. Problems `KEEP` / "
        "`FIX-KEY:X` / `DROP`. Notes optional.",
        "",
        "Note on flags: the giveaway and CAS verifiers are deliberately",
        "conservative (they prefer to flag). Many MUST-REVIEW items are fully",
        "formed and may just need a KEEP; the flag only means the machine could",
        "not auto-clear them.",
        "",
        "---",
        "",
        f"# A. MUST-REVIEW ({len(flagged)})",
        "",
    ]

    body: list[str] = []
    counter = 0
    for key, title in REASON_ORDER:
        grp = by_reason.get(key, [])
        if not grp:
            continue
        grp.sort(key=lambda z: (z["kind"], z["blueprint_area"], z["id"]))
        body.append(f"## {title}  ({len(grp)})\n")
        lines, n = render_bucket(grp, show_flag=True)
        body.extend(lines)
        counter += n

    body.append(f"\n# B. SPOT-CHECK ({len(spot)}) — random sample of clean items\n")
    lines, _ = render_bucket(spot, show_flag=False)
    body.extend(lines)

    out_md = os.path.join(args.dir, "REVIEW-SHEET.md")
    with open(out_md, "w", encoding="utf-8") as fh:
        fh.write("\n".join(head) + "\n" + "\n".join(body))

    manifest = {
        "must_review": {
            "total": len(flagged),
            "by_reason": {k: [x["id"] for x in by_reason.get(k, [])] for k, _ in REASON_ORDER},
        },
        "spot_check": {"total": len(spot), "pct": args.spot_pct,
                       "ids": sorted(x["id"] for x in spot)},
        "clean_total": len(clean),
        "exam_form_ids": sorted(exam_ids),
    }
    json.dump(manifest, open(os.path.join(args.dir, "review_manifest.json"), "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)

    print(f"wrote {out_md}")
    print(f"  MUST-REVIEW: {len(flagged)}  (by reason: "
          f"{ {k: len(by_reason.get(k, [])) for k, _ in REASON_ORDER} })")
    print(f"  SPOT-CHECK: {len(spot)} of {len(clean)} clean (~{args.spot_pct:.0f}%)")


if __name__ == "__main__":
    main()
