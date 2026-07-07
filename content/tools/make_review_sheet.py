"""Generate a disposable human review sheet for the gold sets.

Emits content/gold/REVIEW-SHEET.md: every problem-gold item in sequential order
(then every card-gold item), each with its stem, choices (the draft key marked),
the machine cross-check verdict so the eye goes to the items that need it, and a
blank verdict line for Frank to fill.

This sheet contains real ETS and community question text, so it lives under
git-ignored content/ and is deleted after the review.

Run:
    python content/tools/make_review_sheet.py
"""

from __future__ import annotations

import argparse
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.dirname(HERE)
PROBLEMS = os.path.join(CONTENT, "gold", "problems")
CARDS = os.path.join(CONTENT, "gold", "cards")
OUT = os.path.join(CONTENT, "gold", "REVIEW-SHEET.md")
CARDS_OUT = os.path.join(CONTENT, "gold", "REVIEW-CARDS.md")


def load(directory: str) -> list[dict]:
    out = []
    for name in sorted(os.listdir(directory)):
        if name.endswith(".json"):
            out.append(json.load(open(os.path.join(directory, name), encoding="utf-8")))
    return out


def source_of(item: dict) -> str:
    note = item.get("notes", "")
    if "GR9677" in note or "GR9677" in json.dumps(item.get("provenance", {})):
        return "GR9677 (ETS)"
    if "community" in note:
        return "community-70"
    return "?"


def crosscheck_note(item: dict) -> str:
    v = item.get("verification", {})
    cx = v.get("crosscheck")
    if cx:
        o = cx.get("opinions", {})
        return (f"key check: claimed {o.get('claimed_key')}, gpt-4o {o.get('gpt4o')}, "
                f"gpt-5.5 {o.get('gpt5_5')} -> {cx.get('verdict')}")
    solve = v.get("independent_solve")
    if solve:
        return (f"key check: gpt-4o solved {solve.get('answer')}, "
                f"agrees={solve.get('agrees_with_key')}")
    return "key: authoritative (ETS)"


def problem_block(i: int, p: dict) -> str:
    lines = [f"### {i}. `{p['id']}` — {p['blueprint_area']} — {source_of(p)}", ""]
    lines.append(f"_{crosscheck_note(p)}_")
    lines.append("")
    lines.append(f"**Stem.** {p['stem']}")
    lines.append("")
    for c in p["choices"]:
        mark = "  **← draft key**" if c.get("is_key") else ""
        lines.append(f"- **{c['label']})** {c['text']}{mark}")
    lines.append("")
    lines.append(f"Draft key: **{p['key']}**")
    lines.append("")
    lines.append("- Verdict (KEEP / FIX-KEY:_ / DROP): ")
    lines.append("- Notes: ")
    lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def card_block(i: int, c: dict) -> str:
    lines = [f"### {i}. `{c['id']}` — {c['blueprint_area']} — {c.get('card_kind','')}", ""]
    ref = c.get("provenance", {}).get("source_ref", {})
    src = ref.get("title", "")
    sec = ref.get("section", "")
    lines.append(f"_source: {src} {sec}_")
    lines.append("")
    lines.append(f"**Front.** {c['front']}")
    lines.append("")
    lines.append(f"**Back.** {c['back']}")
    if c.get("fact_assertions"):
        lines.append("")
        lines.append("Facts asserted:")
        for fa in c["fact_assertions"]:
            lines.append(f"- {fa.get('claim','')}")
    lines.append("")
    lines.append("- Verdict (KEEP / FIX / DROP): ")
    lines.append("- Notes: ")
    lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def cards_only() -> None:
    cards = load(CARDS)
    head = [
        "# Card gold review sheet (disposable)",
        "",
        "DELETE THIS FILE after the review. It stays private under content/.",
        "",
        "## How to use",
        "",
        "For each card fill the Verdict line: `KEEP`, `FIX` (say what in Notes), or",
        "`DROP`. These are corpus-grounded cards; check that the fact is correct and",
        "the source ref fits. Notes optional.",
        "",
        "---",
        "",
        f"# Cards ({len(cards)})",
        "",
    ]
    body = [card_block(i, c) for i, c in enumerate(cards, start=1)]
    with open(CARDS_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(head) + "\n" + "".join(body))
    print(f"wrote {CARDS_OUT}  ({len(cards)} cards)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate a disposable gold review sheet.")
    ap.add_argument("--cards-only", action="store_true", help="emit only the card sheet")
    args = ap.parse_args()
    if args.cards_only:
        cards_only()
        return
    problems = load(PROBLEMS)
    cards = load(CARDS)

    # Which problems the machine flagged for attention (not plain consensus).
    flagged = []
    for p in problems:
        cx = p.get("verification", {}).get("crosscheck", {})
        if cx and cx.get("verdict") not in (None, "consensus-key-ok"):
            flagged.append((p["id"], cx.get("verdict")))

    head = [
        "# Gold review sheet (disposable)",
        "",
        "DELETE THIS FILE after the review. It contains real ETS and community",
        "question text and must never be committed.",
        "",
        "## How to use",
        "",
        "For each item, fill the Verdict line. For problems: `KEEP` if the key and",
        "the distractor rationales are right, `FIX-KEY:X` if the correct answer is a",
        "different letter, `DROP` to cut it. For cards: `KEEP`, `FIX` (say what), or",
        "`DROP`. Notes are optional.",
        "",
        "The machine already triangulated every key. The items below are in order;",
        "you can skim the ones marked consensus and slow down on the flagged ones.",
        "",
        f"## Priority: the {len(flagged)} problems the machine did not mark plain consensus",
        "",
    ]
    for pid, verdict in flagged:
        head.append(f"- `{pid}` ({verdict})")
    head += ["", "The rest were unanimous or majority-confirmed; a quick skim is enough.",
             "", "---", "", f"# Problems ({len(problems)})", ""]

    body = [problem_block(i, p) for i, p in enumerate(problems, start=1)]
    card_head = ["", f"# Cards ({len(cards)})", ""]
    card_body = [card_block(i, c) for i, c in enumerate(cards, start=1)]

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(head) + "\n" + "".join(body) + "\n".join(card_head) + "\n" + "".join(card_body))
    print(f"wrote {OUT}")
    print(f"  problems: {len(problems)}  cards: {len(cards)}  flagged: {len(flagged)}")


if __name__ == "__main__":
    main()
