# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for verifier agreement statistics and card serialization."""

from typing import get_type_hints

from anki.pgrep.ai import agreement


def test_raw_agreement_counts_matches():
    assert agreement.raw_agreement([True, True, False], [True, False, False]) == 2 / 3


def test_balanced_accuracy_handles_class_imbalance():
    # 9 easy negatives all right, 1 positive missed -> raw high, balanced low.
    pred = [False] * 9 + [False]
    human = [False] * 9 + [True]
    assert agreement.balanced_accuracy(pred, human) == 0.5


def test_precision_recall():
    prec, rec = agreement.precision_recall([True, True, False], [True, False, True])
    assert prec == 0.5
    assert rec == 0.5


def test_consistency_is_fraction_of_stable_verdicts():
    runs = [[True, True, False], [True, False, False]]  # item 2 flipped
    assert agreement.consistency_score(runs) == 2 / 3


def test_tune_threshold_finds_precision_cutoff():
    conf = [0.9, 0.8, 0.7, 0.6]
    correct = [True, True, False, True]
    # at cutoff 0.8: {0.9,0.8} both correct -> precision 1.0
    assert agreement.tune_threshold(conf, correct, target_precision=1.0) == 0.8


def test_tune_threshold_does_not_split_tied_confidences():
    # Both items share confidence 0.8, one wrong: precision at >=0.8 is 0.5, so a
    # target of 1.0 is unattainable and the cutoff stays 1.0.
    assert agreement.tune_threshold([0.8, 0.8], [True, False], target_precision=1.0) == 1.0


def test_mismatched_lengths_return_nan():
    import math

    assert math.isnan(agreement.balanced_accuracy([True], [True, False]))
    p, r = agreement.precision_recall([True], [True, False])
    assert math.isnan(p) and math.isnan(r)
    assert math.isnan(agreement.consistency_score([[True, True], [True]]))


def test_property_report_and_build_card_serialize():
    rep = agreement.property_report("key", [True, False, True], [True, True, True])
    d = rep.to_dict()
    assert set(d) == {
        "name", "n", "raw_agreement", "balanced_accuracy", "precision", "recall",
    }
    assert d["name"] == "key" and d["n"] == 3
    card = agreement.build_card([rep], consistency=0.9, thresholds={"key": 0.8})
    assert card["consistency"] == 0.9
    assert card["thresholds"] == {"key": 0.8}
    assert card["properties"][0]["name"] == "key"

    missing = agreement.build_card([rep], consistency=None, thresholds={})
    assert missing["consistency"] is None
    assert get_type_hints(agreement.build_card)["consistency"] == float | None
