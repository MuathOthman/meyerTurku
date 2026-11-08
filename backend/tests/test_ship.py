"""Whole-ship checks, machinery escape, and naming that should not call a store a stair."""
import pymupdf
import pytest

from keel.analyze import _cluttered
from keel.checks.machinery import machinery_a_escape, machinery_other_escape
from keel.classify import classify_by_keyword
from keel.extract import Segment
from keel.model import Category, Deck, Door, Space
from keel.rules import load_rules
from keel.ship import Particulars, colreg_values, read_particulars, ship_checks, spaces_needed
from keel.stairs import DetectedStair
from keel.verdict import Verdict
from pathlib import Path

RULES = Path(__file__).resolve().parents[1] / "rules"


@pytest.mark.parametrize(
    "name, category",
    [
        ("DRY LINEN BELOW STAIRWAY", Category.STORES),
        ("BELOW STARWA YR", Category.SERVICE),  # OCR of "below stairway"
        ("CG LOCKER (BELOW STAIRS)", Category.SERVICE),
        ("ENGINEER'S WORKSHOP", Category.SERVICE),
        ("SANITARY CABIN", Category.SANITARY),
        ("ENGINE ROOM", Category.MACHINERY),
        ("ENGINE CONTROL ROOM", Category.CONTROL),
        ("STAIRWAY", Category.STAIR),
    ],
)
def test_names_are_read_as_what_they_are(name, category):
    assert classify_by_keyword(name)[0] == category


def stair_lines(extra=(), grey=False):
    """Six treads 800 long, 250 apart, with two side rails."""
    treads = [Segment(0, y, 800, y, 0.3) for y in range(0, 1500, 250)]
    rails = [Segment(0, 0, 0, 1250, 0.3), Segment(800, 0, 800, 1250, 0.3)]
    return treads + rails + [Segment(*e, 0.1, grey) for e in extra]


STAIR = DetectedStair(box=(0, 0, 800, 1250), width=800, treads=6, spacing=250)


def test_a_plain_stair_is_kept():
    assert not _cluttered(STAIR, stair_lines())


def test_a_winch_drawn_with_bars_is_not_a_stair():
    detail = [(10 + i * 7, 10, 10 + i * 7, 1200) for i in range(100)]
    assert _cluttered(STAIR, stair_lines(detail))


def test_mostly_grey_detail_is_not_a_stair():
    detail = [(10, 10 + i * 100, 790, 10 + i * 100) for i in range(12)]
    assert _cluttered(STAIR, stair_lines(detail, grey=True))


def room(id, name, category, x0, y0, x1, y1, confidence=0.95):
    return Space(
        id=id, name=name, category=category, classification_confidence=confidence,
        anchor_mm=((x0 + x1) / 2, (y0 + y1) / 2),
        exterior_mm=[(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
    )


def deck(spaces, doors=()):
    return Deck(
        name="test", source_pdf="t.pdf", page_index=0, mm_per_pt=1.0, relative_error=0.0,
        extraction_tolerance_mm=10.0, spaces=spaces, doors=list(doors),
    )


def rule(rule_id):
    return next(r for r in load_rules(RULES, ship_type="cargo") if r.id == rule_id)


def door(space_a, space_b, x, y):
    return Door(
        id="D-01", hinge_mm=(x, y), latch_mm=(x + 800, y), leaf_tip_mm=(x, y + 800),
        arc_mid_mm=(x + 560, y + 560), leaf_width_mm=800, space_a=space_a, space_b=space_b,
    )


def test_an_engine_room_with_two_stairs_has_two_means_of_escape():
    engine = room("E", "ENGINE ROOM", Category.MACHINERY, 0, 0, 20000, 10000)
    stairs = [
        room("S1", "Stairway 1", Category.STAIR, 1000, 1000, 2000, 4000),
        room("S2", "Stairway 2", Category.STAIR, 17000, 6000, 18000, 9000),
    ]
    [finding] = machinery_a_escape(deck([engine, *stairs]), rule("ESC-MACH-A-TWO-MEANS"))
    assert finding.verdict == Verdict.PASS
    assert "16.8 m apart" in finding.why  # centres 16 m and 5 m apart


def test_an_engine_room_with_one_stair_goes_to_review_never_fail():
    engine = room("E", "ENGINE ROOM", Category.MACHINERY, 0, 0, 20000, 10000)
    stair = room("S1", "Stairway 1", Category.STAIR, 1000, 1000, 2000, 4000)
    [finding] = machinery_a_escape(deck([engine, stair]), rule("ESC-MACH-A-TWO-MEANS"))
    assert finding.verdict == Verdict.NEEDS_REVIEW


def test_ventilation_for_the_engine_room_is_not_category_a():
    fan = room("V", "ENGINE ROOM VENTILATION", Category.MACHINERY, 0, 0, 3000, 3000)
    assert machinery_a_escape(deck([fan]), rule("ESC-MACH-A-TWO-MEANS")) == []


def test_a_small_room_with_one_door_is_within_the_5_m_walk():
    hpu = room("H", "HPU ROOM", Category.MACHINERY, 0, 0, 3000, 3000)
    deck_ = deck([hpu, room("C", "Corridor", Category.CORRIDOR, 0, -2000, 3000, 0)], [door("H", "C", 1000, 0)])
    [finding] = machinery_other_escape(deck_, rule("ESC-MACH-OTHER-ROUTES"))
    assert finding.verdict == Verdict.PASS
    assert finding.measured_mm < 5000


def test_a_long_room_with_one_door_goes_to_review():
    winch = room("W", "WINCH DRIVE ROOM", Category.MACHINERY, 0, 0, 12000, 3000)
    deck_ = deck([winch, room("C", "Corridor", Category.CORRIDOR, 0, -2000, 3000, 0)], [door("W", "C", 500, 0)])
    [finding] = machinery_other_escape(deck_, rule("ESC-MACH-OTHER-ROUTES"))
    assert finding.verdict == Verdict.NEEDS_REVIEW
    assert finding.measured_mm > 10000


def test_colreg_limits_from_length_and_breadth():
    items = {i.ref: i.detail for i in colreg_values(Particulars(length_overall_m=60, breadth_m=15))}
    assert "Rule 23(a)(ii)" in items
    assert "At least 30 m apart" in items["Annex I 3(a)"]
    assert "no more than 15 m from the stem" in items["Annex I 3(a)"]
    assert "at least 12 m above the hull" in items["Annex I 2(a)(i)"]


def test_a_short_narrow_vessel_needs_one_masthead_light_at_6_m():
    items = {i.ref: i.detail for i in colreg_values(Particulars(length_overall_m=30, breadth_m=5))}
    assert "Rule 23(a)(ii)" not in items
    assert "at least 6 m above the hull" in items["Annex I 2(a)(i)"]


def test_spaces_a_rule_needs_are_found_only_from_printed_names():
    analyses = [{"id": "a", "deck": "MAIN DECK", "spaces": [
        {"name": "SEWAGE TREATMENT ROOM", "number": 3, "name_on_drawing": True},
        {"name": "garbage area", "number": 4, "name_on_drawing": False},
    ]}]
    items = {i.title: i for i in spaces_needed(analyses)}
    assert items["Sewage system"].status == "shown"
    assert items["Sewage system"].where[0]["deck"] == "MAIN DECK"
    # An AI guess is not evidence that a space is on the drawing.
    assert items["Garbage handling"].status == "not_shown"


def test_accessibility_rules_are_listed_as_not_applying_to_a_cargo_ship():
    statuses = {i["regulation"]: i["status"] for i in ship_checks([], Particulars(), "cargo")["items"]}
    assert statuses["ADA"] == statuses["PVAG"] == "not_applicable"
    assert "ADA" not in {i["regulation"] for i in ship_checks([], Particulars(), "passenger")["items"]}


def test_main_dimensions_are_read_from_the_title_block(tmp_path):
    path = tmp_path / "sheet.pdf"
    document = pymupdf.open()
    page = document.new_page(width=800, height=400)
    page.insert_text((50, 50), "60m FISHERY RESEARCH VESSEL")
    for row, (label, value) in enumerate([("LENGTH O.A", "60,00"), ("LENGTH P.P.", "52.20"), ("BREADTH", "15.00")]):
        page.insert_text((100, 120 + row * 20), label)
        page.insert_text((300, 124 + row * 20), value)
    document.save(path)
    found = read_particulars(path)
    assert (found.length_overall_m, found.length_pp_m, found.breadth_m) == (60.0, 52.2, 15.0)
    assert "RESEARCH VESSEL" in found.title


def test_a_narrow_stair_needs_its_arrow():
    from keel.analyze import _looks_like_stair

    narrow = DetectedStair(box=(0, 0, 13, 30), width=13.6, treads=8, spacing=4)  # 600 mm at 44.1 mm/pt
    assert not _looks_like_stair(narrow, [], 44.1)
    assert _looks_like_stair(narrow, [(6, 33)], 44.1)  # arrowhead just past the last tread
    assert not _looks_like_stair(narrow, [(6, 60)], 44.1)  # the arrow of a stair further away


def test_a_stair_of_the_usual_width_is_kept_without_an_arrow():
    from keel.analyze import _looks_like_stair

    wide = DetectedStair(box=(0, 0, 18, 40), width=18.2, treads=10, spacing=4)  # 800 mm
    assert _looks_like_stair(wide, [], 44.1)


class FakeLLM:
    name = "fake"

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def complete_json(self, prompt, schema, images=None):
        self.calls.append((prompt, images))
        return self.answer


def blind_finding(rule_id="ESC-MACH-OTHER-ROUTES"):
    from keel.verdict import Finding

    return Finding(
        rule_id=rule_id, rule_title="t", source="s", value_status="verified", verdict=Verdict.NEEDS_REVIEW,
        subject_id="N05", subject_name="HPU ROOM", source_pdf="p.pdf", page_index=0,
        location_mm=(0, 0), location_pt=(50, 50),
        why="No door was found on this space, so its escape routes cannot be counted.",
        overlay_polygon_pt=[(40, 40), (90, 40), (90, 90), (40, 90)],
    )


def blank_pdf(tmp_path):
    path = tmp_path / "deck.pdf"
    document = pymupdf.open()
    document.new_page(width=300, height=300).draw_rect(pymupdf.Rect(40, 40, 90, 90))
    document.save(path)
    return path


def test_the_ai_looks_where_keel_could_not_measure_but_never_decides(tmp_path):
    from keel.ai_look import look

    finding = blind_finding()
    llm = FakeLLM({"answer": "looks_ok", "seen": "Two doors, one on each side.", "count": 2})
    assert look(blank_pdf(tmp_path), 0, [finding], {"ESC-MACH-OTHER-ROUTES": "machinery_other_escape"}, llm) == 1
    assert finding.verdict == Verdict.NEEDS_REVIEW
    assert finding.ai_look == {"answer": "looks_ok", "seen": "Two doors, one on each side.", "count": 2}
    assert finding.why.startswith("AI looked at the drawing")
    assert "No door was found" in finding.assumptions[0]
    prompt, images = llm.calls[0]
    assert "HPU ROOM" in prompt and images and images[0][:2] == b"\xff\xd8"  # one JPEG of the space


def test_a_failed_ai_call_leaves_the_gap_as_it_was(tmp_path):
    from keel.ai_look import look
    from keel.llm import LLMError

    class Broken(FakeLLM):
        def complete_json(self, prompt, schema, images=None):
            raise LLMError("spend limit")

    finding = blind_finding()
    assert look(blank_pdf(tmp_path), 0, [finding], {"ESC-MACH-OTHER-ROUTES": "machinery_other_escape"}, Broken(None)) == 0
    assert finding.ai_look is None
    assert finding.why.startswith("No door was found")


def test_rules_without_a_question_are_not_sent_to_the_ai(tmp_path):
    from keel.ai_look import look

    llm = FakeLLM({"answer": "looks_ok", "seen": "x", "count": 1})
    assert look(blank_pdf(tmp_path), 0, [blind_finding("ESC-DOOR-WIDTH")], {"ESC-DOOR-WIDTH": "escape_door_width"}, llm) == 0
    assert llm.calls == []


@pytest.mark.parametrize(
    "name, category, evidence, printed, area, kept",
    [
        ("HPU ROOM", Category.MACHINERY, "label_inside", True, 10.7, True),
        ("WC", Category.SANITARY, "label_inside", True, 1.0, True),
        ("NH3", Category.SERVICE, "label_inside", True, 2.1, True),
        ("2M", Category.UNKNOWN, "label_inside", True, 5.6, True),
        ("CTD WINCH", Category.OPEN_DECK, "label_inside", True, 103.9, True),  # names a large deck
        ("Stairway 3", Category.STAIR, "treads", False, 0.9, True),
        ("Hatch cover", Category.SERVICE, "none", False, 2.9, False),
        ("berth/bed", Category.CABIN, "none", False, 1.2, False),
        ("ANTI ROLL TANK", Category.SERVICE, "label_inside", False, 24.8, False),
        ("FO", Category.UNKNOWN, "label_inside", True, 3.0, False),
        ("④", Category.UNKNOWN, "label_inside", True, 0.1, False),
        ("7d", Category.UNKNOWN, "label_inside", True, 6.0, False),
        ("open deck edge/strip", Category.OPEN_DECK, "symbols_only", False, 0.2, False),
        ("narrow open deck passage", Category.OPEN_DECK, "symbols_only", False, 1.4, False),
        ("Unidentified space", Category.UNKNOWN, "none", False, 1.3, False),
        ("Unidentified space", Category.UNKNOWN, "label_inside", False, 88.6, True),  # big: a room to name
    ],
)
def test_only_rooms_stay_in_the_room_list(name, category, evidence, printed, area, kept):
    from keel.analyze import NamedSpace, _non_room_reason

    space = NamedSpace(1, name, None, category, 0.7, evidence, printed, area, (0, 0))
    assert (_non_room_reason(space) is None) == kept


def test_crew_cabin_marks_are_cabins_on_every_deck():
    from keel.analyze import NamedSpace, _set_aside_non_rooms

    kept, _ = _set_aside_non_rooms([NamedSpace(1, "1M", None, Category.UNKNOWN, 0.75, "label_inside", True, 4.6, (0, 0))])
    assert kept[0].category == Category.CABIN


def test_a_tank_set_aside_still_counts_on_the_whole_ship_page():
    analyses = [{"id": "a", "deck": "BELOW MAIN DECK", "spaces": [], "set_aside": [
        {"number": 7, "description": "BILGE SETTL. TANK", "reason": "Tank, void or casing, not a room"},
    ]}]
    items = {i.title: i for i in spaces_needed(analyses)}
    assert items["Oil residue (sludge) tank"].status == "shown"
