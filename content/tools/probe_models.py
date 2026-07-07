"""Probe which OpenAI models answer on the current key.

A one-token call per candidate model, so the authoring runs pin a model that
actually resolves rather than 404-ing 50 calls in. Prints OK or the error per
model. Reads the key from content/.env.

Run:
    conda run -n pgrep-ai python content/tools/probe_models.py
"""

from __future__ import annotations

import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.dirname(HERE)
ENV = os.path.join(CONTENT, ".env")

CANDIDATES = [
    "gpt-5.5-2026-04-23",
    "gpt-5.4-mini-2026-03-17",
    "gpt-5.5",
    "gpt-4o",
    "gpt-4o-mini",
]


def load_key() -> str | None:
    if not os.path.exists(ENV):
        return None
    for line in open(ENV, encoding="utf-8"):
        m = re.match(r"\s*OPENAI_API_KEY\s*=\s*(.+)", line)
        if m and m.group(1).strip() and not m.group(1).strip().startswith("<"):
            return m.group(1).strip()
    return None


def main() -> None:
    key = load_key()
    if not key:
        print("[stop] no OPENAI_API_KEY in content/.env")
        sys.exit(2)
    from openai import OpenAI

    client = OpenAI(api_key=key)
    for model in CANDIDATES:
        t0 = time.time()
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Reply with the single word: ok"}],
                max_completion_tokens=5,
            )
            dt = time.time() - t0
            txt = (resp.choices[0].message.content or "").strip()
            print(f"OK    {model:28} {dt:5.1f}s  -> {txt!r}")
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            short = msg.split("\n")[0][:140]
            print(f"FAIL  {model:28}       {short}")


if __name__ == "__main__":
    main()
