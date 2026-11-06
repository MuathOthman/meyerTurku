"""End to end on the RCRV drawing. Skipped if the PDF has not been downloaded."""
from pathlib import Path

import pytest

from keel.checks import run_checks
from keel.evaluate import evaluate, load_cases
from keel.model import Category
from keel.pipeline import build_deck
from keel.rules import load_rules
from keel.verdict import Verdict

BACKEND = Path(__file__).parents[1]
CONFIG = BACKEND / "data/decks/rcrv_01_level.yaml"
pytestmark = pytest.mark.skipif(not (BACKEND / "data/raw/rcrv_ga.pdf").exists(), reason="drawing not downloaded")


@pytest.fixture(scope="module")
def deck():
    return build_deck(CONFIG)[0]


@pytest.fixture(scope="module")
def rules():
    return load_rules(BACKEND / "rules")


def test_rooms_have_believable_areas(deck):
    cabins = deck.by_category(Category.CABIN)
    assert len(cabins) == 9
    assert all(3.0 < c.area_m2 < 8.0 for c in cabins)


def test_corridor_is_one_space_with_exits(deck):
    corridor = deck.space("01-15-2")
    assert corridor.category == Category.CORRIDOR
    assert len(deck.doors_of(corridor.id)) >= 10


def test_baseline_has_no_fail(deck, rules):
    assert not [f for f in run_checks(deck, rules) if f.verdict == Verdict.FAIL]


def test_evaluation_finds_all_defects_with_no_false_alarms(deck, rules):
    report = evaluate(deck, rules, load_cases(BACKEND / "data/decks/rcrv_01_level_eval.yaml"))
    assert report.found == len(report.defects)
    assert report.false_alarms == 0


def test_injected_widths_are_measured_back(deck, rules):
    report = evaluate(deck, rules, load_cases(BACKEND / "data/decks/rcrv_01_level_eval.yaml"))
    for case in report.cases:
        if case.target_mm is not None:
            assert case.measured_mm == pytest.approx(case.target_mm, abs=5)
