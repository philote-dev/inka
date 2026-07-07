"""Full transcription of all 292 CWRU cards (question and answer) to text.

Reads the rasterized PNGs in examples/cwru/png/, transcribes each with an
OpenAI vision model to clean text with math in LaTeX, strips the small card
footer marker (like "1-CM"), and fills question_text and answer_text in
examples/cwru/cards.json.

Resilient by design:
  - Checks OPENAI_API_KEY first; stops cleanly if missing (no loud failure).
  - Idempotent: a card with both texts already filled is skipped, so a re-run
    only processes what is left (or what failed).
  - Retries each image a few times with backoff.
  - Saves cards.json incrementally, so a crash never loses finished work.
  - Records failures to examples/cwru/transcription_failures.json for re-run.
  - Tracks token usage and prints an approximate cost.

This is for the EXAMPLES pool. Before any CWRU card enters a shipped deck or a
gold set it still needs the ETS-dedup scan against tier3-private.

Run:
    conda run -n pgrep-ai python content/tools/transcribe_cwru_full.py
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CWRU = os.path.join(ROOT, "examples", "cwru")
PNG_DIR = os.path.join(CWRU, "png")
CARDS = os.path.join(CWRU, "cards.json")
FAILS = os.path.join(CWRU, "transcription_failures.json")
ENV = os.path.join(ROOT, ".env")

MODEL = "gpt-4o"
# gpt-4o public pricing per 1M tokens (approx): input 2.50 USD, output 10.00 USD.
COST_IN = 2.50 / 1_000_000
COST_OUT = 10.00 / 1_000_000
MAX_RETRY = 4
SAVE_EVERY = 5

PROMPT = (
    "You are transcribing a physics flashcard image to clean text. "
    "Reproduce the wording exactly. Render every equation, symbol, subscript, "
    "superscript, and Greek letter in LaTeX, inline with \\( \\) and display "
    "with \\[ \\]. Do NOT include the small card index or footer marker printed "
    "in a corner (for example '1-CM', '23-QM', a page number). Do not solve or "
    "add commentary. Output only the transcription."
)

# Safety net for the footer marker if the model still emits it: a trailing
# token like "1-CM", "23 - QM", possibly on its own line at the very end.
FOOTER = re.compile(r"\s*\n?\s*\d{1,3}\s*[-\u2013\u2014]\s*[A-Za-z]{2,4}\s*$")


def log(msg: str) -> None:
    print(msg, flush=True)


def load_key() -> str | None:
    if not os.path.exists(ENV):
        return None
    for line in open(ENV):
        line = line.strip()
        if line.startswith("OPENAI_API_KEY="):
            val = line.split("=", 1)[1].strip()
            return val or None
    return None


def data_url(png_name: str) -> str:
    with open(os.path.join(PNG_DIR, png_name), "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:image/png;base64,{b64}"


def strip_footer(text: str) -> str:
    return FOOTER.sub("", text).strip()


class Usage:
    def __init__(self) -> None:
        self.pin = 0
        self.pout = 0

    def add(self, resp) -> None:
        u = getattr(resp, "usage", None)
        if u:
            self.pin += getattr(u, "prompt_tokens", 0) or 0
            self.pout += getattr(u, "completion_tokens", 0) or 0

    def cost(self) -> float:
        return self.pin * COST_IN + self.pout * COST_OUT


def transcribe(client, png_name: str, usage: Usage) -> str:
    last = None
    for attempt in range(1, MAX_RETRY + 1):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": PROMPT},
                            {"type": "image_url", "image_url": {"url": data_url(png_name)}},
                        ],
                    }
                ],
                temperature=0,
            )
            usage.add(resp)
            return strip_footer(resp.choices[0].message.content.strip())
        except Exception as e:  # noqa: BLE001
            last = e
            wait = 2 * attempt
            log(f"    [retry {attempt}/{MAX_RETRY}] {png_name}: {e} (wait {wait}s)")
            time.sleep(wait)
    raise RuntimeError(f"{png_name} failed after {MAX_RETRY} tries: {last}")


def main() -> None:
    key = load_key()
    if not key:
        log("[stop] OPENAI_API_KEY missing or empty in content/.env. Needed to "
            "transcribe. Nothing changed.")
        sys.exit(0)

    from openai import OpenAI

    client = OpenAI(api_key=key)
    cards = json.load(open(CARDS))
    todo = [c for c in cards if not (c["question_text"] and c["answer_text"])]
    log(f"[start] {len(todo)} cards to transcribe, {len(cards) - len(todo)} already done")

    usage = Usage()
    failures = []
    done = 0
    for i, c in enumerate(todo, start=1):
        cid = c["id"]
        try:
            if not c["question_text"]:
                c["question_text"] = transcribe(client, c["question_png"], usage)
            if not c["answer_text"]:
                c["answer_text"] = transcribe(client, c["answer_png"], usage)
            done += 1
            log(f"[{i}/{len(todo)}] ok {cid}  (cost so far ${usage.cost():.2f})")
        except Exception as e:  # noqa: BLE001
            failures.append({"id": cid, "error": str(e)})
            log(f"[{i}/{len(todo)}] FAIL {cid}: {e}")
        if i % SAVE_EVERY == 0:
            json.dump(cards, open(CARDS, "w"), indent=1)

    json.dump(cards, open(CARDS, "w"), indent=1)
    json.dump(failures, open(FAILS, "w"), indent=1)

    total = sum(1 for c in cards if c["question_text"] and c["answer_text"])
    log("\n[summary]")
    log(f"  transcribed this run: {done}")
    log(f"  total complete:       {total}/{len(cards)}")
    log(f"  failed:               {len(failures)}")
    log(f"  tokens in/out:        {usage.pin}/{usage.pout}")
    log(f"  approx cost:          ${usage.cost():.2f}")
    if failures:
        log(f"  failures recorded in: {FAILS} (re-run this script to retry them)")


if __name__ == "__main__":
    main()
