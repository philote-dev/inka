"""Pull a small slice of the public anki-revlogs-10k dataset to verify fit.

Memory calibration (L5.1) needs a revlog: predicted retrievability vs actual
pass/fail, time-ordered. This downloads a few users' revlog parquet files, prints
the schema and basic distributions so Frank can confirm it fits before we commit
to it, and stages the sample under content/heldout/anki-revlogs-sample/.

Public dataset (open-spaced-repetition/anki-revlogs-10k), CC-licensed. Run:
    conda run -n pgrep-ai --no-capture-output python content/tools/fetch_revlog_sample.py
"""

from __future__ import annotations

import os
import shutil
from collections import Counter

import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.dirname(HERE)
REPO = "open-spaced-repetition/anki-revlogs-10k"
DEST = os.path.join(CONTENT, "heldout", "anki-revlogs-sample")
USERS = [1, 100, 1000, 5000]


def grab(path: str) -> str | None:
    try:
        return hf_hub_download(REPO, path, repo_type="dataset")
    except Exception as exc:  # noqa: BLE001
        print(f"  [skip] {path}: {str(exc)[:80]}")
        return None


def main() -> None:
    os.makedirs(DEST, exist_ok=True)
    readme = grab("README.md")
    if readme:
        shutil.copy(readme, os.path.join(DEST, "DATASET-README.md"))

    schema_printed = False
    total_rows = 0
    ratings = Counter()
    per_user = {}
    tmin = tmax = None

    for uid in USERS:
        local = grab(f"revlogs/user_id={uid}/data.parquet")
        if not local:
            continue
        shutil.copy(local, os.path.join(DEST, f"revlogs_user_{uid}.parquet"))
        t = pq.read_table(local)
        cols = t.column_names
        if not schema_printed:
            print("[schema] revlogs columns:")
            for f in t.schema:
                print(f"   {f.name}: {f.type}")
            schema_printed = True
        n = t.num_rows
        per_user[uid] = n
        total_rows += n
        d = t.to_pydict()
        rating_col = next((c for c in cols if c.lower() in ("rating", "button_chosen", "ease")), None)
        if rating_col:
            ratings.update(d[rating_col])
        time_col = next((c for c in cols if "time" in c.lower() or c.lower() in ("id", "timestamp")), None)
        if time_col:
            vals = [v for v in d[time_col] if v is not None]
            if vals:
                lo, hi = min(vals), max(vals)
                tmin = lo if tmin is None else min(tmin, lo)
                tmax = hi if tmax is None else max(tmax, hi)

    print(f"\n[sample] users fetched: {list(per_user)}")
    print(f"[sample] rows per user: {per_user}")
    print(f"[sample] total review rows: {total_rows}")
    print(f"[sample] rating/button distribution: {dict(sorted(ratings.items())) if ratings else 'n/a'}")
    print(f"[sample] time-col range: {tmin} .. {tmax}")
    print(f"[staged] {DEST}")


if __name__ == "__main__":
    main()
