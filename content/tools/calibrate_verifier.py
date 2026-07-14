"""Calibrate the verifier panel against a per-property human-labeled set (WS6).

Reads a per-property human-labels JSON, runs the panel, compares per property via
``pgrep.ai.agreement``, tunes each gate's confidence threshold for the target
accept-precision, and writes the calibration card and thresholds under
``content/run/calibration/``.

Run the offline smoke:
    conda run -n pgrep-ai --no-capture-output \
        python content/tools/calibrate_verifier.py --self-check
The full labeled-set run (``--labels``) lands once the ~120-item human set exists.
"""

from __future__ import annotations

import argparse
import json

import _ai_path  # noqa: E402

_ai_path.add_ai_core()

from pgrep.ai import agreement  # type: ignore[import-not-found]  # noqa: E402


def _self_check() -> int:
    pred = [True, True, False, True]
    human = [True, False, False, True]
    rep = agreement.property_report("key", pred, human)
    card = agreement.build_card([rep], consistency=1.0, thresholds={"key": 0.8})
    assert card["properties"][0]["name"] == "key"
    print("[ok] calibrate_verifier self-check passed")
    print(json.dumps(card, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Calibrate the verifier panel.")
    ap.add_argument("--labels", help="path to the per-property human labels JSON")
    ap.add_argument("--out", default="content/run/calibration")
    ap.add_argument(
        "--self-check", action="store_true", help="run an offline smoke and exit"
    )
    args = ap.parse_args()
    if args.self_check:
        return _self_check()
    if not args.labels:
        ap.error("--labels is required unless --self-check is given")
    # The full labeled-set run (load labels + problems, run the panel per item,
    # collect per-property predictions, tune thresholds, write the card) lands with
    # the ~120-item human calibration set. The panel and stats it calls are done.
    raise SystemExit("labeled-set run: provide --labels once the calibration set exists")


if __name__ == "__main__":
    raise SystemExit(main())
