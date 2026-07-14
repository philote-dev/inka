"""Build a disposable human review sheet for foundry-escalated problems.

The foundry loop routes low-confidence panel verdicts to ``escalated.json``.
This script turns that list into a Markdown sheet in the shared review contract:
``### <id>`` blocks ending in ``-> your call: ESCALATE|KEEP|DROP``. Fill the
slots, then apply verdicts in a follow-up pass.

Writes ``escalation.md`` next to the input JSON (or ``--out``).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import review_sheet  # noqa: E402


def recommend(_it: dict) -> str:
    return "ESCALATE"


def block(it: dict) -> str:
    stem = str(it.get("stem", ""))
    preview = stem[:80] + ("..." if len(stem) > 80 else "")
    return (
        f"### {it['id']}\n"
        f"reason: {it.get('reason', '')}\n"
        f"stem: {preview}\n"
        f"-> your call: {recommend(it)}\n"
        "---\n"
    )


def render_escalation_sheet(items: list[dict]) -> str:
    """Render the escalation review sheet for ``items``."""
    head = [
        "# Foundry escalation",
        "",
        "Fill each `-> your call:` line. Tokens: `ESCALATE` (needs human review), "
        "`KEEP` (accept into the bundle path), `DROP` (discard).",
        "",
        f"- **{len(items)} to review** below. Default recommendation is ESCALATE.",
        "",
        "---",
        "",
    ]
    return review_sheet.build(
        items,
        header=head,
        recommend=recommend,
        block=block,
        id_of=lambda it: it["id"],
    )


def load_escalated(path: str) -> list[dict]:
    """Load escalated items from a bare list or ``{escalated: [...]}`` wrapper."""
    data = json.load(open(path, encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("escalated"), list):
        return data["escalated"]
    raise SystemExit(f"expected a list or {{escalated: [...]}} in {path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--input",
        help="Path to escalated.json (default: content/run/foundry/<run>/escalated.json)",
    )
    ap.add_argument(
        "--run",
        default="latest",
        help="Foundry run directory name under content/run/foundry/ (default: latest)",
    )
    ap.add_argument(
        "--out",
        help="Output markdown path (default: escalation.md beside the input JSON)",
    )
    args = ap.parse_args()

    if args.input:
        inp = args.input
    else:
        base = os.path.join("content", "run", "foundry")
        if args.run == "latest":
            runs = sorted(
                d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))
            )
            if not runs:
                raise SystemExit(f"no runs under {base}")
            run_dir = os.path.join(base, runs[-1])
        else:
            run_dir = os.path.join(base, args.run)
        inp = os.path.join(run_dir, "escalated.json")

    items = load_escalated(inp)
    items.sort(key=lambda it: it.get("id", ""))

    out = args.out or os.path.join(os.path.dirname(inp), "escalation.md")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    md = render_escalation_sheet(items)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(md)

    manifest_path = os.path.join(os.path.dirname(out), "escalation.manifest.json")
    json.dump(
        review_sheet.manifest(items, recommend=recommend, id_of=lambda it: it["id"]),
        open(manifest_path, "w", encoding="utf-8"),
        indent=2,
        ensure_ascii=False,
    )
    print(f"escalated {len(items)}; wrote {out}")


if __name__ == "__main__":
    main()
