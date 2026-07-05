# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Contract tests for the L5 pgrep JSON bridge handlers (Channel B).

The three L5.5 handlers (``pgrep_performance_score``, ``pgrep_readiness_score``,
``pgrep_calibration``) are thin ``_json(...)`` wrappers over the pure-Python
engine. These tests pin the contract the web surfaces rely on: each handler is
registered, is reachable at the camelCased endpoint the frontend calls, and
returns JSON-decodable bytes of the expected shape. They run against a fresh
empty collection, so they also demonstrate the honest n=1 abstain state (empty
attempt log -> Performance and Readiness abstain, while Calibration still ships
its embedded evidence).
"""

from __future__ import annotations

import json
import os
import tempfile
import types

import pytest

import aqt
from anki.collection import Collection
from aqt import mediasrv, pgrep


@pytest.fixture
def col():
    fd, path = tempfile.mkstemp(suffix=".anki2")
    os.close(fd)
    os.unlink(path)
    collection = Collection(path)
    try:
        yield collection
    finally:
        collection.close()


@pytest.fixture
def bridge(col, monkeypatch):
    """Point the handlers at a real empty collection with an empty JSON body."""
    monkeypatch.setattr(aqt, "mw", types.SimpleNamespace(col=col), raising=False)
    # The handlers that read args (_args) use flask's request.data; a request
    # context with an empty body makes _args() return {}.
    with mediasrv.app.test_request_context(data=b"{}"):
        yield


# --- registration + naming ---------------------------------------------------


def test_new_handlers_are_registered():
    for handler in (
        pgrep.pgrep_performance_score,
        pgrep.pgrep_readiness_score,
        pgrep.pgrep_calibration,
    ):
        assert handler in pgrep.pgrep_post_handlers


def test_handlers_reachable_at_the_frontend_endpoints():
    # mediasrv exposes each handler at POST /_anki/<camelCase(name)>; the Progress
    # surface calls exactly these names via pgrepCall.
    for endpoint in (
        "pgrepPerformanceScore",
        "pgrepReadinessScore",
        "pgrepCalibration",
    ):
        assert endpoint in mediasrv.post_handlers


# --- handler payloads (shape + honest n=1 state) -----------------------------


def test_performance_handler_returns_expected_shape(bridge):
    data = json.loads(pgrep.pgrep_performance_score())

    assert set(data) == {
        "overall",
        "by_topic",
        "k_perf",
        "coverage_pct",
        "coverage_gate",
        "last_updated",
    }
    # n=1 reality: empty attempt log -> the overall Performance abstains.
    assert data["overall"]["abstain"] is True
    assert data["last_updated"] is None


def test_readiness_handler_returns_expected_shape_and_abstains(bridge):
    data = json.loads(pgrep.pgrep_readiness_score())

    for key in (
        "scaled",
        "low",
        "high",
        "coverage_pct",
        "coverage_gate",
        "abstain",
        "reason",
        "uncovered_topics",
        "by_topic",
    ):
        assert key in data, f"missing key: {key}"
    # Coverage is 0 with no attempts, so Readiness abstains and names the exam.
    assert data["abstain"] is True
    assert data["scaled"] is None
    assert data["coverage_pct"] == 0.0
    assert data["reason"] == "Not enough of the exam is covered yet"
    assert len(data["uncovered_topics"]) > 0


def test_calibration_handler_returns_embedded_evidence(bridge):
    data = json.loads(pgrep.pgrep_calibration())

    assert set(data) >= {"memory", "performance"}
    for layer_name in ("memory", "performance"):
        layer = data[layer_name]
        for key in ("points", "brier", "n", "note"):
            assert key in layer, f"{layer_name} missing key: {key}"
        assert layer["points"], f"{layer_name} should ship reliability points"
        for point in layer["points"]:
            assert set(point) == {"p", "o"}
    # The embedded evidence is present regardless of the (empty) collection.
    assert round(data["memory"]["brier"], 3) == 0.234
    assert round(data["performance"]["brier"], 3) == 0.175


def test_calibration_handler_needs_no_collection():
    # Calibration is pure embedded constants: it must work without aqt.mw.col set.
    data = json.loads(pgrep.pgrep_calibration())
    assert data["memory"]["n"] == 7503
    assert data["performance"]["n"] == 160
