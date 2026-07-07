"""Transcribe a SMALL SAMPLE of CWRU cards with an OpenAI vision model.

Sample only (cost control): one Classical Mechanics, one Quantum, one Ray
Optics card, each question and answer. Writes the text back into cards.json for
those cards and a human-readable TRANSCRIPTION-SAMPLE.md so Frank can judge
quality before committing to all 292.

Reads the key from content/.env (OPENAI_API_KEY). Math is requested in LaTeX.

Run:
    conda run -n pgrep-ai python content/tools/transcribe_cwru_sample.py
"""

from __future__ import annotations

import base64
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CWRU = os.path.join(ROOT, "examples", "cwru")
PNG_DIR = os.path.join(CWRU, "png")
ENV = os.path.join(ROOT, ".env")

SAMPLE_IDS = [
    "classical-mechanics-01",
    "quantum-mechanics-and-atomic-physics-01",
    "ray-optics-01",
]
MODEL = "gpt-4o"
PROMPT = (
    "You are transcribing a physics flashcard image to clean text. "
    "Reproduce the wording exactly. Render every equation, symbol, subscript, "
    "superscript, and Greek letter in LaTeX, inline with \\( \\) and display "
    "with \\[ \\]. Do not solve or add commentary. Output only the "
    "transcription."
)


def load_key() -> str | None:
    for line in open(ENV):
        line = line.strip()
        if line.startswith("OPENAI_API_KEY="):
            return line.split("=", 1)[1].strip()
    return None


def data_url(png_name: str) -> str:
    with open(os.path.join(PNG_DIR, png_name), "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:image/png;base64,{b64}"


def transcribe(client, png_name: str) -> str:
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
    return resp.choices[0].message.content.strip()


def main() -> None:
    key = load_key()
    if not key:
        print("[skip] no OPENAI_API_KEY in content/.env; transcription pending")
        return
    from openai import OpenAI

    client = OpenAI(api_key=key)
    cards = json.load(open(os.path.join(CWRU, "cards.json")))
    by_id = {c["id"]: c for c in cards}

    md = ["# CWRU Transcription Sample (3 cards)\n"]
    md.append(
        "Vision transcription of 3 cards (question and answer), math in LaTeX, "
        f"model `{MODEL}`. Judge quality before full transcription.\n"
    )
    for cid in SAMPLE_IDS:
        c = by_id[cid]
        print(f"[transcribe] {cid} ...")
        q = transcribe(client, c["question_png"])
        a = transcribe(client, c["answer_png"])
        c["question_text"] = q
        c["answer_text"] = a
        md.append(f"\n## {c['category']} ({cid})\n")
        md.append(f"**Question images:** `png/{c['question_png']}` / `png/{c['answer_png']}`\n")
        md.append(f"\n**Question**\n\n{q}\n")
        md.append(f"\n**Answer**\n\n{a}\n")

    json.dump(cards, open(os.path.join(CWRU, "cards.json"), "w"), indent=1)
    open(os.path.join(CWRU, "TRANSCRIPTION-SAMPLE.md"), "w").write("\n".join(md))
    print("[done] wrote sample into cards.json and TRANSCRIPTION-SAMPLE.md")


if __name__ == "__main__":
    main()
