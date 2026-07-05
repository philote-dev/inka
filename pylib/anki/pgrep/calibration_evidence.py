# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Embedded model-calibration evidence (aggregate statistics, constants only).

The honest dashboard (Feature 4, ``feature-calibration.md``) shows each of the
two model layers with its calibration evidence: a **reliability diagram** (the
predicted vs observed points) plus a **Brier** score. Those numbers come from
offline evaluations on held-out data:

- **Memory** — FSRS-6 retrievability ``R`` against actual recall on held-out
  reviews (L5.1; ``content/run/memory_calibration_results.json``). We ship the
  **default (as-shipped) FSRS** curve, not the secondary per-user recalibration:
  pgrep serves raw FSRS ``R``, so the honest curve is the default one, which is
  slightly overconfident.
- **Performance** — ``P(correct)`` against held-out exam-style outcomes (L5.2;
  ``content/run/performance_results.json``). The synthetic study validates the
  *pipeline / methodology*, not a real-cohort population.

Like :mod:`anki.pgrep.readiness_constants`, this module embeds those results as
**tracked constants**. The values are aggregate statistics (binned reliability
points and a Brier score), which are plain factual measurements, not the private
source data. The private ``content/`` tree is **gitignored and absent in the
shipped app**, so nothing on the calibration path reads it at runtime; the
leakage firewall stays green (a test asserts this module never opens a file or
references a private root). Regenerate the numbers below (never hand-edit) from
the offline result JSONs if a re-run changes them; ``test_pgrep_calibration_evidence.py``
pins them to those JSONs when ``content/`` is present.
"""

from __future__ import annotations

from typing import Any

__all__ = ["calibration_evidence"]


# --- Memory: default FSRS-6 on held-out reviews (L5.1) -----------------------
#
# Source: ``content/run/memory_calibration_results.json`` -> ``overall``.
# ``MEMORY_RELIABILITY_POINTS`` mirrors ``overall.reliability_points`` (equal-mass
# bins, ``(predicted_mean, observed_recall)``); ``MEMORY_BRIER`` is
# ``overall.fsrs.brier.point`` (the DEFAULT FSRS, not ``recalibrated_fsrs``);
# ``MEMORY_N`` is ``overall.n_test``.

MEMORY_RELIABILITY_POINTS: tuple[tuple[float, float], ...] = (
    (0.5537578246385091, 0.31025299600532624),
    (0.6818266360154652, 0.5446071904127829),
    (0.7481109235814282, 0.596537949400799),
    (0.8029890985095504, 0.708),
    (0.8379842805075447, 0.7653333333333333),
    (0.8648675644832492, 0.7546666666666667),
    (0.8875462455797204, 0.756),
    (0.9106683994243087, 0.7786666666666666),
    (0.9392564305080099, 0.7386666666666667),
    (0.9798395923438424, 0.668),
)
MEMORY_BRIER = 0.23376769284759738
MEMORY_N = 7503
MEMORY_SOURCE = (
    "Held-out reviews from the anki-revlogs-10k sample (4 users, time-split)"
)
MEMORY_METHOD = (
    "Default FSRS-6 (fsrs-rs 5.2.0) retrievability vs recall; binning-free Brier"
)
MEMORY_DATE = "2026-07-05"
MEMORY_NOTE = "Validated on held-out reviews. Default FSRS, slightly overconfident."


# --- Performance: held-out synthetic pipeline validation (L5.2) --------------
#
# Source: ``content/run/performance_results.json`` -> ``model`` (the shipped
# ``pfa_beta_calibrated``). ``PERFORMANCE_RELIABILITY_POINTS`` mirrors
# ``model.reliability`` as ``(mean_pred, mean_obs)``; ``PERFORMANCE_BRIER`` is
# ``model.brier.point``; ``PERFORMANCE_N`` is ``model.n`` (the held-out split).
# The synthetic study validates the methodology, not population coefficients, so
# the honest read is "methodology validated on held-out synthetic (n=1 cohort)".

PERFORMANCE_RELIABILITY_POINTS: tuple[tuple[float, float], ...] = (
    (0.42041089306686397, 0.3125),
    (0.6417704111662867, 0.75),
    (0.7552744918905231, 0.625),
    (0.8183745451592563, 0.75),
    (0.8628029972318318, 0.8125),
    (0.8898958087171822, 0.9375),
    (0.9184974003972319, 0.9375),
    (0.9331065135300922, 0.75),
    (0.946382250923898, 0.6875),
    (0.9597583033785975, 0.875),
)
PERFORMANCE_BRIER = 0.17523368467276343
PERFORMANCE_N = 160
PERFORMANCE_SOURCE = "Held-out synthetic exam-style outcomes (pipeline validation)"
PERFORMANCE_METHOD = (
    "PFA logistic + beta calibration on a held-out split; binning-free Brier"
)
PERFORMANCE_DATE = "2026-07-05"
PERFORMANCE_NOTE = "Methodology validated on held-out synthetic (n=1 cohort)."


def _points(pairs: tuple[tuple[float, float], ...]) -> list[dict[str, float]]:
    """Reliability pairs -> the ``[{p, o}]`` shape the frontend diagram consumes."""
    return [{"p": p, "o": o} for p, o in pairs]


def _layer(
    pairs: tuple[tuple[float, float], ...],
    brier: float,
    n: int,
    note: str,
    source: str,
    method: str,
    date: str,
) -> dict[str, Any]:
    return {
        "points": _points(pairs),
        "brier": brier,
        "n": n,
        "note": note,
        "source": source,
        "method": method,
        "date": date,
    }


def calibration_evidence() -> dict[str, Any]:
    """Return the embedded calibration evidence for the two model layers.

    JSON-serializable: ``{"memory": {...}, "performance": {...}}``, each carrying
    the reliability ``points`` (``[{p, o}]``), the ``brier`` score, the sample
    ``n``, a short honest ``note`` (the caption), and the provenance (``source``,
    ``method``, ``date``). A fresh dict is built on each call, so callers cannot
    mutate the module constants. No collection, no I/O, no ``content/`` access:
    the numbers are embedded aggregate statistics.
    """
    return {
        "memory": _layer(
            MEMORY_RELIABILITY_POINTS,
            MEMORY_BRIER,
            MEMORY_N,
            MEMORY_NOTE,
            MEMORY_SOURCE,
            MEMORY_METHOD,
            MEMORY_DATE,
        ),
        "performance": _layer(
            PERFORMANCE_RELIABILITY_POINTS,
            PERFORMANCE_BRIER,
            PERFORMANCE_N,
            PERFORMANCE_NOTE,
            PERFORMANCE_SOURCE,
            PERFORMANCE_METHOD,
            PERFORMANCE_DATE,
        ),
    }
