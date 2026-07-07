"""Build a disposable human rating sheet for touchpoint 2 (rater 1).

Frank rates the AI-generated items blind (no LLM-judge verdicts shown), so we can
compute the human rater-1 gate numbers and inter-rater agreement (Cohen's kappa)
against the judge. Only the AI items with content are listed (refused items have
nothing to rate and stay judged not-useful).

Each generated item is NEW (the gold item is only the topic seed, not the answer),
so rate each on its own merits, solving problems yourself. Private, git-ignored;
delete after the ratings are applied.

Run:
    python content/tools/make_rating_sheet.py
"""

from __future__ import annotations

import json
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.dirname(HERE)
CANDIDATES = os.path.join(CONTENT, "run", "candidates.json")
OUT = os.path.join(CONTENT, "gold", "RATING-SHEET.md")


def card_block(n: int, it: dict) -> str:
    lines = [f"### C{n}. `{it.get('target_id')}`  [{it.get('blueprint_area','')}]", ""]
    lines.append(f"**Front.** {it.get('front','')}")
    lines.append("")
    lines.append(f"**Back.** {it.get('back','')}")
    lines.append("")
    lines.append("- useful (y/n): ")
    lines.append("- facts_ok (y/n): ")
    lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def problem_block(n: int, it: dict) -> str:
    lines = [f"### P{n}. `{it.get('target_id')}`  [{it.get('blueprint_area','')}]", ""]
    lines.append(f"**Stem.** {it.get('stem','')}")
    lines.append("")
    for i, c in enumerate(it.get("choices", [])):
        lab = "ABCDE"[i] if i < 5 else str(i)
        lines.append(f"- **{lab})** {c}")
    lines.append("")
    lines.append(f"Generated key: **{it.get('key','')}**")
    lines.append("")
    lines.append("- key_correct (y/n): ")
    lines.append("- useful (y/n): ")
    lines.append("- distractors_ok (y/n): ")
    lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    cands = json.load(open(CANDIDATES, encoding="utf-8"))
    ai = [c for c in cands if c.get("system") == "ai" and not c.get("refused")]
    cards = [c for c in ai if c.get("kind") == "card"]
    probs = [c for c in ai if c.get("kind") == "problem"]
    rng = random.Random(7)
    rng.shuffle(cards)
    rng.shuffle(probs)

    head = [
        "# AI batch rating sheet (disposable, touchpoint 2)",
        "",
        "DELETE after ratings are applied. Private ETS/community-free content, but",
        "keep it out of git anyway.",
        "",
        "## How to rate",
        "",
        "Rate each generated item on its own merits (each is a NEW item; solve",
        "problems yourself). Fill each line with `y` or `n`.",
        "",
        "- **useful**: correct AND it actually teaches or tests the point (not vague,",
        "  trivial, or off-target).",
        "- **facts_ok** (cards): every asserted fact is correct, no wrong-fact.",
        "- **key_correct** (problems): the marked key is the correct answer.",
        "- **distractors_ok** (problems): all four wrong choices are plausible,",
        "  misconception-grounded, and distinct.",
        "",
        "Rate as many as you can; even a subset gives a valid kappa. The LLM judge's",
        "verdicts are deliberately not shown, so this is blind.",
        "",
        "---",
        "",
        f"# Cards ({len(cards)})",
        "",
    ]
    body = [card_block(i, c) for i, c in enumerate(cards, start=1)]
    phead = ["", f"# Problems ({len(probs)})", ""]
    pbody = [problem_block(i, c) for i, c in enumerate(probs, start=1)]

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(head) + "\n" + "".join(body) + "\n".join(phead) + "\n" + "".join(pbody))
    print(f"wrote {OUT}")
    print(f"  AI cards to rate: {len(cards)}   AI problems to rate: {len(probs)}")
    print(f"  (refused AI items excluded: {sum(1 for c in cands if c.get('system')=='ai' and c.get('refused'))})")


if __name__ == "__main__":
    main()
