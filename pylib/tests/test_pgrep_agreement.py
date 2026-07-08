# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

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
