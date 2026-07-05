# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the embedded pgrep calibration evidence (L5.5).

``anki.pgrep.calibration_evidence`` ships the two model layers' calibration
evidence (reliability points + Brier) as tracked constants, mirroring how
``readiness_constants`` embeds the raw->scaled table. The numbers are aggregate
statistics from the offline evaluations, so the shipped app never reads the
private ``content/`` tree at runtime.

The match tests pin the embedded numbers to those offline result JSONs when they
are present (they are gitignored, so the tests skip cleanly in a checkout without
``content/``). The rest cover the accessor contract and the AI-off / no-runtime-IO
firewall, which do not depend on ``content/``.
"""

from __future__ import annotations

import inspect
import json
import math
from pathlib import Path

import pytest

from anki.pgrep import calibration_evidence
from anki.pgrep.calibration_evidence import (
    MEMORY_BRIER,
    MEMORY_N,
    MEMORY_RELIABILITY_POINTS,
    PERFORMANCE_BRIER,
    PERFORMANCE_N,
    PERFORMANCE_RELIABILITY_POINTS,
)

# The offline results live in the shared (gitignored) content tree at the repo
# root: pylib/tests -> pylib -> repo root -> content/run.
_CONTENT_RUN = Path(__file__).resolve().parents[2] / "content" / "run"


def _load_results(name: str) -> dict:
    path = _CONTENT_RUN / name
    if not path.exists():
        pytest.skip(f"private offline results not present: {path}")
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


# --- match tests: embedded constants == the offline result JSONs -------------


def test_memory_evidence_matches_offline_results():
    overall = _load_results("memory_calibration_results.json")["overall"]

    # Brier is the DEFAULT (as-shipped) FSRS, not the recalibrated secondary.
    assert math.isclose(MEMORY_BRIER, overall["fsrs"]["brier"]["point"], abs_tol=1e-12)
    assert MEMORY_N == overall["n_test"]

    expected = [(pt["p"], pt["o"]) for pt in overall["reliability_points"]]
    assert len(MEMORY_RELIABILITY_POINTS) == len(expected)
    for (emb_p, emb_o), (exp_p, exp_o) in zip(MEMORY_RELIABILITY_POINTS, expected):
        assert math.isclose(emb_p, exp_p, abs_tol=1e-12)
        assert math.isclose(emb_o, exp_o, abs_tol=1e-12)


def test_memory_curve_is_default_fsrs_not_recalibrated():
    # The locked decision: ship the honest default curve (slightly overconfident),
    # never the recalibrated secondary. Guard a regeneration that swaps them.
    overall = _load_results("memory_calibration_results.json")["overall"]
    default0 = overall["reliability"][0]
    recal0 = overall["reliability_recalibrated"][0]
    emb_p0, _ = MEMORY_RELIABILITY_POINTS[0]

    assert math.isclose(emb_p0, default0["p_mean"], abs_tol=1e-9)
    assert not math.isclose(emb_p0, recal0["p_mean"], abs_tol=1e-3)
    # The default Brier is higher (worse) than the recalibrated one; embedding it
    # keeps the dashboard honest about the shipped model's overconfidence.
    assert MEMORY_BRIER > overall["recalibrated_fsrs"]["brier"]["point"]


def test_performance_evidence_matches_offline_results():
    model = _load_results("performance_results.json")["model"]

    assert math.isclose(PERFORMANCE_BRIER, model["brier"]["point"], abs_tol=1e-12)
    assert PERFORMANCE_N == model["n"]

    expected = [(b["mean_pred"], b["mean_obs"]) for b in model["reliability"]]
    assert len(PERFORMANCE_RELIABILITY_POINTS) == len(expected)
    for (emb_p, emb_o), (exp_p, exp_o) in zip(PERFORMANCE_RELIABILITY_POINTS, expected):
        assert math.isclose(emb_p, exp_p, abs_tol=1e-12)
        assert math.isclose(emb_o, exp_o, abs_tol=1e-12)


# --- embedded-constant integrity (no offline data needed) --------------------


def test_reliability_points_are_ordered_and_in_the_unit_square():
    for pairs in (MEMORY_RELIABILITY_POINTS, PERFORMANCE_RELIABILITY_POINTS):
        assert len(pairs) == 10  # equal-mass 10-bin reliability diagram
        predicted = [p for p, _ in pairs]
        assert predicted == sorted(predicted)  # predicted mean rises per bin
        for p, o in pairs:
            assert 0.0 <= p <= 1.0
            assert 0.0 <= o <= 1.0


def test_briers_and_counts_are_sane():
    assert 0.0 < MEMORY_BRIER < 1.0
    assert 0.0 < PERFORMANCE_BRIER < 1.0
    # The task's headline evidence values (~0.234 Memory, ~0.175 Performance).
    assert round(MEMORY_BRIER, 3) == 0.234
    assert round(PERFORMANCE_BRIER, 3) == 0.175
    assert MEMORY_N == 7503
    assert PERFORMANCE_N == 160


# --- accessor contract (the JSON the bridge serializes) ----------------------


def test_accessor_returns_the_expected_shape():
    evidence = calibration_evidence.calibration_evidence()

    assert set(evidence) >= {"memory", "performance"}
    for layer_name in ("memory", "performance"):
        layer = evidence[layer_name]
        for key in ("points", "brier", "n", "note"):
            assert key in layer, f"{layer_name} missing key: {key}"
        assert isinstance(layer["points"], list) and layer["points"]
        for point in layer["points"]:
            assert set(point) == {"p", "o"}
            assert 0.0 <= point["p"] <= 1.0
            assert 0.0 <= point["o"] <= 1.0
        assert isinstance(layer["brier"], float) and 0.0 < layer["brier"] < 1.0
        assert isinstance(layer["n"], int) and layer["n"] > 0
        assert isinstance(layer["note"], str) and layer["note"]

    # The bridge handler returns json.dumps(...) of this, so it must serialize.
    json.dumps(evidence)


def test_accessor_returns_fresh_copies():
    # Callers (and the bridge) must not be able to mutate the module constants.
    first = calibration_evidence.calibration_evidence()
    first["memory"]["points"].append({"p": 0.0, "o": 0.0})
    first["memory"]["brier"] = -1.0

    second = calibration_evidence.calibration_evidence()
    assert len(second["memory"]["points"]) == len(MEMORY_RELIABILITY_POINTS)
    assert second["memory"]["brier"] == MEMORY_BRIER


# --- AI-off + constants-only firewall ----------------------------------------


def test_ai_off_no_ai_or_heavy_imports():
    source = inspect.getsource(calibration_evidence)
    forbidden = (
        "pgrep.ai",
        "import openai",
        "import anthropic",
        "import httpx",
        "import requests",
        "import torch",
        "import numpy",
        "import pandas",
        "import scipy",
        "urllib",
    )
    for token in forbidden:
        assert token not in source, f"unexpected import {token}"


def test_constants_only_never_reads_content_at_runtime():
    # "Constants only": the shipped module embeds aggregate statistics and must
    # not open a file or read the private content tree at runtime (it is gitignored
    # and absent in the shipped app). The docstring may *name* the source JSONs for
    # provenance, but there is no I/O machinery on the scoring path.
    source = inspect.getsource(calibration_evidence)
    assert "open(" not in source
    assert "json.load" not in source
    assert "import json" not in source
    assert "pathlib" not in source
