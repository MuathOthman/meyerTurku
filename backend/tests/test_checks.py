"""Every check on a small synthetic deck: corridor with two exits and one cabin."""
from pathlib import Path

import pytest
from shapely.geometry import box

from keel.checks import run_checks
from keel.classify import LLM_CONFIDENCE_CAP, classify, classify_by_keyword
from keel.explain import note_is_safe
from keel.graph import build_graph, independent_exit_routes
from keel.impact import cabin_impact
from keel.inject import add_cabins, flip_door_swing, lengthen_dead_end, narrow_corridor, remove_exits, shrink_door
from keel.model import Category, Deck, Door, Space
from keel.rules import Rule, load_rules
from keel.verdict import Verdict

RULES = load_rules(Path(__file__).parents[1] / "rules")


def rect_space(id_, name, category, b, berths=0, accessible=False):
    x0, y0, x1, y1 = b
    return Space(
        id=id_, name=name, category=category, classification_confidence=1.0,
        anchor_mm=((x0 + x1) / 2, (y0 + y1) / 2), berths=berths, accessible=accessible,
        exterior_mm=list(box(*b).exterior.coords),
    )


def make_deck(corridor_width=1200.0, stair_width=1000.0):
    w = corridor_width
    spaces = [
        rect_space("C", "PASSAGE", Category.CORRIDOR, (0, 0, 10000, w)),
        rect_space("S", "STAIR", Category.STAIR, (10000, 0, 13000, stair_width)),
        rect_space("O", "DECK", Category.OPEN_DECK, (-5000, -5000, 0, 5000)),
        rect_space("K", "CABIN", Category.CABIN, (2000, w, 5000, w + 3000), berths=2),
    ]
    doors = [
        Door(id="D-S", hinge_mm=(10000, 0), latch_mm=(10000, 800), leaf_tip_mm=(10800, 0),
             arc_mid_mm=(10570, 230), leaf_width_mm=800, space_a="C", space_b="S", swings_into="S"),
        Door(id="D-O", hinge_mm=(0, 0), latch_mm=(0, 800), leaf_tip_mm=(-800, 0),
             arc_mid_mm=(-570, 230), leaf_width_mm=800, space_a="C", space_b="O", swings_into="O"),
        Door(id="D-K", hinge_mm=(3000, w), latch_mm=(3800, w), leaf_tip_mm=(3000, w + 800),
             arc_mid_mm=(3570, w + 570), leaf_width_mm=800, space_a="C", space_b="K", swings_into="K"),
    ]
    return Deck(
        name="test", source_pdf="t.pdf", page_index=0, mm_per_pt=70.0, relative_error=0.0002,
        extraction_tolerance_mm=25.0, spaces=spaces, doors=doors, persons_other_decks=10,
    )


def verdict(findings, rule, subject):
    for f in findings:
        if f.rule_id == rule and f.subject_id == subject:
            return f.verdict
    raise AssertionError(f"no finding {rule} {subject}")


def test_compliant_deck_has_no_fail():
    findings = run_checks(make_deck(), RULES)
    assert findings
    assert not [f for f in findings if f.verdict == Verdict.FAIL]


def test_every_finding_carries_evidence():
    for f in run_checks(make_deck(), RULES):
        assert f.source and f.rule_id and f.why and f.source_pdf
        assert f.value_status in ("verified", "assumed")
        if f.measured_mm is not None:
            assert f.required_mm is not None and f.tolerance_mm is not None
            assert "mm" in f.measured_display and "'" in f.measured_display


def test_narrow_corridor_fails_with_real_measurement():
    findings = run_checks(narrow_corridor(make_deck(), "C", 700), RULES)
    target = next(f for f in findings if f.rule_id == "ESC-CORRIDOR-WIDTH" and f.subject_id == "C")
    assert target.verdict == Verdict.FAIL
    assert target.measured_mm == pytest.approx(700, abs=5)


def test_corridor_width_borderline_goes_to_review():
    findings = run_checks(narrow_corridor(make_deck(), "C", 905), RULES)
    assert verdict(findings, "ESC-CORRIDOR-WIDTH", "C") == Verdict.NEEDS_REVIEW


def test_side_branch_cannot_fail():
    deck = make_deck(corridor_width=1200)
    corridor = deck.space("C")
    # A 700 mm wide branch leads to a cabin door.
    branched = corridor.polygon().union(box(2000, 1200, 2700, 4000))
    corridor.exterior_mm = list(branched.exterior.coords)
    deck.spaces[3].exterior_mm = list(box(2000, 4000, 5000, 7000).exterior.coords)
    door = deck.door("D-K")
    door.hinge_mm, door.latch_mm = (2000, 4000), (2700, 4000)
    findings = run_checks(deck, RULES)
    assert verdict(findings, "ESC-CORRIDOR-WIDTH", "C") == Verdict.PASS
    assert verdict(findings, "ESC-CORRIDOR-WIDTH", "C/branch") == Verdict.NEEDS_REVIEW


def test_stair_width_pass_and_fail():
    assert verdict(run_checks(make_deck(stair_width=1000), RULES), "ESC-STAIR-WIDTH", "S") == Verdict.PASS
    assert verdict(run_checks(make_deck(stair_width=700), RULES), "ESC-STAIR-WIDTH", "S") == Verdict.FAIL


def test_stair_capacity_formula():
    findings = run_checks(make_deck(), RULES)
    target = next(f for f in findings if f.rule_id == "ESC-STAIR-CAPACITY")
    # (2 berths + 10 on the adjoining deck) x 10 mm.
    assert target.required_mm == 120
    assert target.verdict == Verdict.PASS


def test_stair_capacity_fails_with_many_cabins():
    findings = run_checks(add_cabins(make_deck(), 60), RULES)
    assert verdict(findings, "ESC-STAIR-CAPACITY", "S") == Verdict.FAIL


def test_shrunk_door_fails():
    findings = run_checks(shrink_door(make_deck(), "D-S", 600), RULES)
    assert verdict(findings, "ESC-DOOR-WIDTH", "D-S") == Verdict.FAIL


def test_flipped_escape_door_fails_and_names_direction():
    findings = run_checks(flip_door_swing(make_deck(), "D-S"), RULES)
    assert verdict(findings, "ESC-DOOR-SWING", "D-S") == Verdict.FAIL
    assert "against the direction of escape" in next(f.why for f in findings if f.subject_id == "D-S" and f.rule_id == "ESC-DOOR-SWING")


def test_cabin_door_is_exempt_from_swing_rule():
    findings = run_checks(flip_door_swing(make_deck(), "D-K"), RULES)
    assert not [f for f in findings if f.rule_id == "ESC-DOOR-SWING" and f.subject_id == "D-K"]


def test_unreadable_swing_goes_to_review():
    deck = make_deck()
    deck.door("D-S").direction_confident = False
    assert verdict(run_checks(deck, RULES), "ESC-DOOR-SWING", "D-S") == Verdict.NEEDS_REVIEW


def test_two_means_pass_and_fail():
    assert verdict(run_checks(make_deck(), RULES), "ESC-TWO-MEANS", "C") == Verdict.PASS
    assert verdict(run_checks(remove_exits(make_deck(), ["D-O"]), RULES), "ESC-TWO-MEANS", "C") == Verdict.FAIL


def test_route_through_a_cabin_is_not_a_second_means_of_escape():
    deck = remove_exits(make_deck(), ["D-O"])
    deck.doors.append(
        Door(id="D-KO", hinge_mm=(2000, 2000), latch_mm=(2000, 2800), leaf_tip_mm=(1200, 2000),
             arc_mid_mm=(1430, 2230), leaf_width_mm=800, space_a="K", space_b="O", swings_into="O")
    )
    assert verdict(run_checks(deck, RULES), "ESC-TWO-MEANS", "C") == Verdict.FAIL


def test_dead_end_spur_fails():
    findings = run_checks(lengthen_dead_end(make_deck(), "C", 10000), RULES)
    assert verdict(findings, "ESC-DEAD-END", "C") == Verdict.FAIL


def test_accessibility_rules_skip_unmarked_spaces():
    findings = run_checks(make_deck(), [r for r in RULES if r.scope == "accessibility"])
    assert findings == []


def test_accessibility_rules_run_on_marked_space():
    deck = make_deck()
    deck.space("C").accessible = True
    deck.door("D-S").leaf_width_mm = 760
    findings = run_checks(deck, [r for r in RULES if r.scope == "accessibility"])
    assert verdict(findings, "ACC-DOOR-CLEAR", "D-S") == Verdict.FAIL
    assert verdict(findings, "ACC-ROUTE-WIDTH", "C") == Verdict.PASS


def test_turning_space_shortfall_goes_to_review():
    deck = make_deck()
    deck.space("K").accessible = True
    deck.spaces[3].exterior_mm = list(box(2000, 1200, 3000, 3000).exterior.coords)
    findings = run_checks(deck, [r for r in RULES if r.check == "accessible_turning"])
    assert findings[0].verdict == Verdict.NEEDS_REVIEW


def test_low_confidence_room_cannot_fail():
    deck = make_deck()
    deck.space("C").classification_confidence = LLM_CONFIDENCE_CAP
    findings = run_checks(narrow_corridor(deck, "C", 700), RULES)
    assert verdict(findings, "ESC-CORRIDOR-WIDTH", "C") == Verdict.NEEDS_REVIEW


def test_injection_leaves_original_unchanged():
    deck = make_deck()
    before = deck.model_dump_json()
    narrow_corridor(deck, "C", 700)
    flip_door_swing(deck, "D-S")
    assert deck.model_dump_json() == before


def test_graph_routes_stop_at_exits():
    deck = make_deck()
    graph = build_graph(deck)
    assert independent_exit_routes(graph, "C", {"S", "O"}) == ["O", "S"]


def test_impact_lists_notifications_and_new_fail():
    impact_map = {"cabin": {"rules": [{"ref": "x", "why": "y"}], "notify": [{"discipline": "HVAC", "why": "z"}]}}
    result = cabin_impact(make_deck(), RULES, impact_map, count=60)
    assert result.persons_added == 120
    assert [f.rule_id for f in result.newly_failing] == ["ESC-STAIR-CAPACITY"]
    assert result.notify[0]["discipline"] == "HVAC"


def test_keyword_classification():
    assert classify_by_keyword("PASSAGEWAY") == (Category.CORRIDOR, 0.95)
    assert classify_by_keyword("CHIEF SCIENCE")[0] == Category.CABIN
    assert classify_by_keyword("XYZ") is None


class FakeLLM:
    name = "fake"

    def complete_json(self, prompt, schema, images=None):
        return {"rooms": [{"name": "GYM", "category": "service", "confidence": 0.99}]}


def test_llm_confidence_is_capped_so_ai_alone_cannot_fail():
    result = classify(["GYM", "PASSAGEWAY"], FakeLLM())
    assert result["GYM"] == (Category.SERVICE, LLM_CONFIDENCE_CAP)
    assert LLM_CONFIDENCE_CAP < 0.8
    assert result["PASSAGEWAY"][0] == Category.CORRIDOR


def test_classify_without_llm_leaves_unknown():
    assert classify(["GYM"], None)["GYM"] == (Category.UNKNOWN, 0.0)


def test_explanation_with_invented_number_is_rejected():
    finding = run_checks(narrow_corridor(make_deck(), "C", 700), RULES)[0]
    assert note_is_safe("Check why the corridor is narrow.", finding)
    assert not note_is_safe("The corridor should really be 1234 mm wide.", finding)


def test_rule_file_rejects_unknown_fields():
    with pytest.raises(ValueError):
        Rule(id="x", title="t", source="s", type="numeric", scope="s", applies_to=[], parameter="p",
             value_status="assumed", check="c", surprise=1)


def test_rule_with_nothing_to_check_says_so_instead_of_staying_silent():
    deck = make_deck()
    deck.spaces = [s for s in deck.spaces if s.category != Category.CORRIDOR]
    findings = run_checks(deck, [r for r in RULES if r.id == "ESC-CORRIDOR-WIDTH"])
    assert len(findings) == 1
    assert findings[0].verdict == Verdict.NEEDS_REVIEW
    assert "could not be applied" in findings[0].why


def test_unmarked_accessibility_rules_are_not_reported_as_unchecked():
    assert run_checks(make_deck(), [r for r in RULES if r.scope == "accessibility"]) == []


def test_review_text_states_the_real_reason():
    from keel.checks.common import numeric_why

    within = numeric_why(Verdict.NEEDS_REVIEW, "Width", 890, 900, 25, ">=")
    assert "within the 25 mm tolerance" in within
    uncertain = numeric_why(Verdict.NEEDS_REVIEW, "Width", 846, 900, 25, ">=")
    assert "misses by 54 mm" in uncertain
    assert "within the" not in uncertain
