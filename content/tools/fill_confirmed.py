"""Fill the one placeholder distractor left on cross-check-confirmed items.

When gpt-4o's independent solve slipped, it wrote the key rationale for its own
(wrong) pick and left that choice without a distractor annotation. After the
cross-check confirms the real key (community, backed by gpt-5.5), that choice is a
distractor and needs its misconception tag and rationale. This authors just that
one choice per affected item.

Only touches items whose status is pending-frank (key already trusted). Items
still needs-frank-key (an unresolved key) are left for Frank first. Idempotent.

Run:
    conda run -n pgrep-ai --no-capture-output python content/tools/fill_confirmed.py
"""

from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.dirname(HERE)
PROBLEMS = os.path.join(CONTENT, "gold", "problems")
ENV = os.path.join(CONTENT, ".env")

MODEL = "gpt-4o"
MAX_RETRY = 4
PLACEHOLDER = {"pending", "PENDING", "unspecified", ""}

SYS = (
    "You are a physics GRE item writer. For ONE labelled distractor of a "
    "multiple-choice problem whose correct key is given, write the misconception "
    "it encodes. Return STRICT JSON: {\"misconception_tag\": short kebab-case tag "
    "(e.g. sign-error, wrong-law, unit-slip, limiting-case-confusion), "
    "\"rationale\": one sentence naming the specific error that lands a student on "
    "this choice}. Ground it in standard physics."
)


def log(m: str) -> None:
    print(m, flush=True)


def load_key() -> str | None:
    if not os.path.exists(ENV):
        return None
    for line in open(ENV, encoding="utf-8"):
        line = line.strip()
        if line.startswith("OPENAI_API_KEY="):
            return line.split("=", 1)[1].strip() or None
    return None


def placeholder_distractors(item: dict) -> list[dict]:
    out = []
    for c in item["choices"]:
        if c.get("is_key"):
            continue
        if (c.get("misconception_tag") or "").strip() in PLACEHOLDER or \
           (c.get("rationale") or "").strip() in PLACEHOLDER:
            out.append(c)
    return out


def author(client, item: dict, choice: dict) -> dict:
    key = item["key"]
    key_rat = next((c.get("rationale", "") for c in item["choices"] if c["label"] == key), "")
    payload = {
        "stem": item["stem"],
        "choices": {c["label"]: c["text"] for c in item["choices"]},
        "correct_key": key,
        "why_key_is_correct": key_rat,
        "distractor_label": choice["label"],
    }
    last = None
    for attempt in range(1, MAX_RETRY + 1):
        try:
            resp = client.chat.completions.create(
                model=MODEL, temperature=0, response_format={"type": "json_object"},
                messages=[{"role": "system", "content": SYS},
                          {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}])
            return json.loads(resp.choices[0].message.content)
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2 * attempt)
    raise RuntimeError(f"fill failed after {MAX_RETRY}: {last}")


def main() -> None:
    key = load_key()
    if not key:
        log("[stop] no OPENAI_API_KEY in content/.env")
        sys.exit(0)

    files = sorted(f for f in os.listdir(PROBLEMS) if f.endswith(".json"))
    todo = []
    for name in files:
        path = os.path.join(PROBLEMS, name)
        it = json.load(open(path, encoding="utf-8"))
        if it.get("verification", {}).get("status") != "pending-frank":
            continue
        if placeholder_distractors(it):
            todo.append((path, it))
    log(f"[start] filling placeholder distractors on {len(todo)} confirmed items")
    if not todo:
        return

    from openai import OpenAI
    client = OpenAI(api_key=key)
    done = 0
    for i, (path, it) in enumerate(todo, start=1):
        try:
            for choice in placeholder_distractors(it):
                ann = author(client, it, choice)
                choice["misconception_tag"] = str(ann.get("misconception_tag", "")).strip() or "unspecified"
                choice["rationale"] = str(ann.get("rationale", "")).strip() or "pending"
            note = it["verification"].get("note", "")
            it["verification"]["note"] = note + " Distractor for gpt-4o's slipped pick authored after cross-check confirmed the key."
            json.dump(it, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            done += 1
            log(f"[{i}/{len(todo)}] filled {it['id']}")
        except Exception as exc:  # noqa: BLE001
            log(f"[{i}/{len(todo)}] FAIL {it['id']}: {exc}")
    log(f"\n[done] filled {done}/{len(todo)}")


if __name__ == "__main__":
    main()
