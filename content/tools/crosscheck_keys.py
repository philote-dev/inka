"""Independent key cross-check for the community problem gold (Touchpoint 1).

The community keys are forum-sourced, so each one gets a second independent solve
by a STRONGER model (gpt-5.5), independent of the gpt-4o annotator. Combined with
the gpt-4o solve already on file and the claimed key, every key gets three
opinions, which resolves most disagreements without Frank solving from scratch:

  - all three agree                    -> key trusted (consensus)
  - claimed == gpt-5.5, gpt-4o differs -> key trusted, gpt-4o slipped
  - claimed == gpt-4o, gpt-5.5 differs -> key trusted, gpt-5.5 dissents
  - gpt-4o == gpt-5.5, claimed differs -> claimed key LIKELY WRONG, Frank decides
  - all three differ                   -> hard, Frank decides

GR9677 keys are authoritative ETS (official solutions), so they are not re-solved
here; they are trusted and only spot-checked by Frank.

Writes each verdict into the item's verification.crosscheck and updates the
status. Idempotent (cached per source id). Run:
    conda run -n pgrep-ai --no-capture-output python content/tools/crosscheck_keys.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.dirname(HERE)
PROBLEMS = os.path.join(CONTENT, "gold", "problems")
CACHE_DIR = os.path.join(CONTENT, "gold", "candidates", "_xcheck_cache")
ENV = os.path.join(CONTENT, ".env")

MODEL = "gpt-5.5-2026-04-23"
MAX_RETRY = 4

SYS = (
    "You are solving one Physics GRE multiple-choice problem. Work it out from "
    "physics. Then answer. Return STRICT JSON only: "
    '{"answer": "A"|"B"|"C"|"D"|"E", "reason": "one short sentence", '
    '"confidence": 0..1}. Do not include anything else.'
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


def source_id(item: dict) -> str:
    for tok in item.get("notes", "").split(";"):
        tok = tok.strip()
        if tok.startswith("source_id="):
            return tok.split("=", 1)[1].strip()
    return item["id"]


def is_community(item: dict) -> bool:
    return "community-70" in item.get("notes", "")


def parse_letter(text: str) -> str:
    try:
        data = json.loads(text)
        a = str(data.get("answer", "")).strip().upper()[:1]
        if a in "ABCDE":
            return a, data.get("reason", ""), data.get("confidence")
    except (json.JSONDecodeError, AttributeError):
        pass
    m = re.search(r"\b([A-E])\b", text or "")
    return (m.group(1) if m else "?"), (text or "")[:120], None


def solve(client, item: dict):
    payload = {"stem": item["stem"], "choices": {c["label"]: c["text"] for c in item["choices"]}}
    user = json.dumps(payload, ensure_ascii=False)
    last = None
    for attempt in range(1, MAX_RETRY + 1):
        try:
            try:
                resp = client.chat.completions.create(
                    model=MODEL, response_format={"type": "json_object"},
                    messages=[{"role": "system", "content": SYS}, {"role": "user", "content": user}])
            except Exception:  # some reasoning snapshots reject response_format; retry plain
                resp = client.chat.completions.create(
                    model=MODEL,
                    messages=[{"role": "system", "content": SYS}, {"role": "user", "content": user}])
            return parse_letter(resp.choices[0].message.content or "")
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2 * attempt)
    raise RuntimeError(f"solve failed after {MAX_RETRY}: {last}")


def verdict(claimed: str, gpt4o: str, gpt55: str) -> tuple[str, str]:
    s = {claimed, gpt4o, gpt55}
    if len(s) == 1:
        return "consensus-key-ok", "pending-frank"
    if claimed == gpt55 and gpt4o != claimed:
        return "key-ok-gpt4o-slip", "pending-frank"
    if claimed == gpt4o and gpt55 != claimed:
        return "key-ok-gpt55-dissent", "pending-frank"
    if gpt4o == gpt55 and claimed != gpt4o:
        return "key-likely-wrong", "needs-frank-key"
    return "hard-3way", "needs-frank-key"


def main() -> None:
    ap = argparse.ArgumentParser(description="Independent gpt-5.5 key cross-check (community gold).")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    key = load_key()
    if not key:
        log("[stop] no OPENAI_API_KEY in content/.env")
        sys.exit(0)

    files = sorted(f for f in os.listdir(PROBLEMS) if f.endswith(".json"))
    items = [(os.path.join(PROBLEMS, f), json.load(open(os.path.join(PROBLEMS, f), encoding="utf-8")))
             for f in files]
    community = [(p, it) for p, it in items if is_community(it)]
    if args.limit:
        community = community[: args.limit]
    log(f"[start] cross-checking {len(community)} community keys with {MODEL}")

    from openai import OpenAI
    client = OpenAI(api_key=key)
    os.makedirs(CACHE_DIR, exist_ok=True)

    tally, flags, done = {}, [], 0
    for i, (path, it) in enumerate(community, start=1):
        sid = source_id(it)
        cache = os.path.join(CACHE_DIR, f"{sid}.json")
        try:
            if os.path.exists(cache):
                cx = json.load(open(cache, encoding="utf-8"))
            else:
                ans, reason, conf = solve(client, it)
                cx = {"answer": ans, "reason": reason, "confidence": conf}
                json.dump(cx, open(cache, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            claimed = it["key"]
            gpt4o = (it.get("verification", {}).get("independent_solve", {}) or {}).get("answer", "?")
            gpt55 = cx["answer"]
            vname, status = verdict(claimed, gpt4o, gpt55)
            it["verification"]["crosscheck"] = {
                "model": MODEL, "answer": gpt55, "reason": cx.get("reason"),
                "confidence": cx.get("confidence"), "verdict": vname,
                "opinions": {"claimed_key": claimed, "gpt4o": gpt4o, "gpt5_5": gpt55}}
            it["verification"]["status"] = status
            json.dump(it, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            tally[vname] = tally.get(vname, 0) + 1
            if status == "needs-frank-key":
                flags.append((it["id"], sid, claimed, gpt4o, gpt55, vname))
            done += 1
            log(f"[{i}/{len(community)}] {it['id']} ({sid}) claim={claimed} 4o={gpt4o} 5.5={gpt55} -> {vname}")
        except Exception as exc:  # noqa: BLE001
            log(f"[{i}/{len(community)}] FAIL {it['id']} ({sid}): {exc}")

    log("\n[summary]")
    log(f"  cross-checked: {done}/{len(community)}")
    for v, n in sorted(tally.items()):
        log(f"   {v:22} {n}")
    log(f"\n  items still needing Frank's key call: {len(flags)}")
    for pid, sid, claimed, g4, g5, v in flags:
        log(f"   {pid} ({sid}): claim {claimed}, gpt-4o {g4}, gpt-5.5 {g5}  [{v}]")


if __name__ == "__main__":
    main()
