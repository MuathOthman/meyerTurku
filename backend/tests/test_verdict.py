import pytest

from keel.verdict import Verdict, geometric_verdict, margin_mm, numeric_verdict


def test_margin_sign_follows_operator():
    assert margin_mm(1000, 900, ">=") == 100
    assert margin_mm(6000, 7000, "<=") == 1000
    with pytest.raises(ValueError):
        margin_mm(1, 1, "==")


def test_clear_pass_and_clear_fail():
    assert numeric_verdict(1000, 900, ">=", 25) == Verdict.PASS
    assert numeric_verdict(800, 900, ">=", 25) == Verdict.FAIL


@pytest.mark.parametrize("measured", [876, 880, 900, 920, 925])
def test_within_tolerance_goes_to_review_never_fail(measured):
    assert numeric_verdict(measured, 900, ">=", 25) == Verdict.NEEDS_REVIEW


def test_low_applicability_cannot_fail():
    assert numeric_verdict(500, 900, ">=", 25, applicability_confidence=0.5) == Verdict.NEEDS_REVIEW


def test_low_classification_cannot_fail():
    assert numeric_verdict(500, 900, ">=", 25, classification_confidence=0.75) == Verdict.NEEDS_REVIEW


def test_upper_limit_rules():
    assert numeric_verdict(8000, 7000, "<=", 100) == Verdict.FAIL
    assert numeric_verdict(6000, 7000, "<=", 100) == Verdict.PASS


def test_geometric_verdict_needs_confidence_to_decide():
    assert geometric_verdict(True) == Verdict.PASS
    assert geometric_verdict(False) == Verdict.FAIL
    assert geometric_verdict(False, applicability_confidence=0.0) == Verdict.NEEDS_REVIEW
