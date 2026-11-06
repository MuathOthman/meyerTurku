"""The new-drawing flow, on a synthetic plan image, so no network or PDF is needed."""
import cv2
import numpy as np
import pytest

from keel.analyze import (
    Analysis,
    NamedSpace,
    analysis_json,
    analyze,
    checklist_for,
    load_applicability,
    name_is_printed,
)
from keel.classify import classify_by_keyword
from keel.llm import LLMError
from keel.model import Category
from keel.raster import extract_walls, segment
from keel.score import score
from keel.spaces import detect_wall_widths, is_vector_page
from keel.extract import Segment


def plan_image():
    """Two rooms split by a wall, with a door gap, on a white sheet."""
    image = np.full((600, 1000), 255, np.uint8)
    cv2.rectangle(image, (100, 100), (900, 500), 0, 4)
    cv2.line(image, (500, 100), (500, 294), 0, 4)
    cv2.line(image, (500, 306), (500, 500), 0, 4)  # A narrow gap, like a door on a real plan.
    return image


def test_walls_survive_and_hairlines_do_not():
    image = plan_image()
    cv2.line(image, (150, 150), (450, 450), 0, 1)
    walls = extract_walls(image)
    assert walls[100, 300] == 255
    assert walls[300, 300] == 0


def test_segment_splits_rooms_at_the_door_gap():
    result = segment(plan_image(), neck_px=110.0)
    assert len(result.spaces) == 2
    assert result.labels[300, 300] != result.labels[300, 700]


def test_wall_widths_exclude_text_and_hairlines():
    segments = [Segment(0, 0, 500, 0, 0.36), Segment(0, 5, 300, 5, 0.27)]
    segments += [Segment(0, 9, 3, 9, 0.18)] * 200  # letter strokes are short
    segments += [Segment(0, 8, 400, 8, 0.06)]  # hairline
    assert detect_wall_widths(segments) == (0.27, 0.36)


def test_image_file_is_not_a_vector_page(tmp_path):
    assert is_vector_page(tmp_path / "x.png") is False


def test_stair_arrows_and_marks_are_not_room_names():
    from types import SimpleNamespace as Block

    from keel.analyze import _is_room_text

    for mark in ("UP", "DN", "~DN", "J", "45", "PLAN 7-4A 02 LEVEL", ""):
        assert not _is_room_text(Block(name=mark)), mark
    for name in ("GALLEY", "W/C", "2ND MATE", "LN LKR"):
        assert _is_room_text(Block(name=name)), name


def test_name_must_really_be_printed():
    printed = ["MAIN LAB 1-33-0", "GALLEY"]
    assert name_is_printed("MAIN LAB", printed)
    assert name_is_printed("GALEY", printed)
    assert not name_is_printed("ENGINE ROOM", printed)


def test_ship_vocabulary_needs_no_ai():
    assert classify_by_keyword("2ND MATE")[0] == Category.CABIN
    assert classify_by_keyword("CAPTAIN")[0] == Category.CABIN
    assert classify_by_keyword("FROZEN STORES")[0] == Category.STORES
    assert classify_by_keyword("CG LOCKER (BELOW STAIRS)")[0] == Category.SERVICE


def test_every_space_type_has_a_checklist():
    table = load_applicability()
    for category in Category:
        assert table.get(category.value), f"no checklist for {category.value}"
        for entry in table[category.value]:
            assert entry["ref"] and entry["what"] and "confirmed" in entry


def test_checklist_is_fixed_by_type_and_marks_unconfirmed_references():
    items = checklist_for(Category.GALLEY, load_applicability(), [], "N01", set())
    assert any("13.3.2.3" in i.ref and i.confirmed_reference for i in items)
    assert any(not i.confirmed_reference for i in items)
    assert all(i.status == "to_check" for i in items)


class NamingLLM:
    name = "fake"

    def __init__(self):
        self.calls = 0

    def complete_json(self, prompt, schema, images=None):
        self.calls += 1
        assert images, "naming must look at the drawing"
        return {
            "spaces": [
                {"number": 1, "name": "ENGINE ROOM", "compartment": "", "category": "machinery", "is_room": True, "confidence": 0.99, "evidence": "symbols_only"},
                {"number": 2, "name": "A SOFA", "compartment": "", "category": "unknown", "is_room": False, "confidence": 0.9, "evidence": "none"},
            ]
        }


def write_plan(tmp_path):
    path = tmp_path / "plan.png"
    cv2.imwrite(str(path), plan_image())
    return path


def test_analyze_an_image_end_to_end_with_no_fail_possible(tmp_path):
    result = analyze(write_plan(tmp_path), NamingLLM())
    assert result.route == "raster"
    engine = next(s for s in result.spaces if s.name == "ENGINE ROOM")
    # The AI said 0.99, but it is not printed on the drawing, so it is not trusted.
    assert engine.confidence <= 0.4
    assert engine.name_on_drawing is False
    assert any("13.4" in item.ref for item in engine.checklist)
    assert "No scale" in result.scale_note
    body = analysis_json(result)
    assert body["reviewed"] is False
    assert all(item["verdict"] is None for s in body["spaces"] for item in s["checklist"])


def test_ai_cannot_silently_remove_a_large_space(tmp_path):
    result = analyze(write_plan(tmp_path), NamingLLM())
    assert 2 in [s.number for s in result.spaces]


def test_without_ai_spaces_are_still_found_and_reported(tmp_path):
    result = analyze(write_plan(tmp_path), None)
    assert len(result.spaces) == 2
    assert all(s.name == "Unidentified space" for s in result.spaces)
    assert "No LLM" in result.naming_error
    unknown = result.spaces[0].checklist[0]
    assert "could not identify" in unknown.what


class FailingLLM:
    name = "fails"

    def complete_json(self, prompt, schema, images=None):
        raise LLMError("HTTP 429", retryable=True)


def test_ai_failure_is_reported_not_hidden(tmp_path):
    result = analyze(write_plan(tmp_path), FailingLLM())
    assert "failed" in result.naming_error
    assert len(result.spaces) == 2


def test_unreadable_file_is_an_error(tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image")
    with pytest.raises(ValueError):
        analyze(bad, None)


def test_score_counts_names_and_misses(tmp_path):
    labels = np.zeros((100, 100), dtype=np.int32)
    labels[10:40, 10:40] = 1
    labels[60:90, 60:90] = 2
    space = NamedSpace(1, "MAIN LAB", None, Category.LAB, 0.7, "label_inside", True, None, (20, 20))
    result = Analysis("x", 0, "raster", "", None, None, [space], [], np.zeros((1, 1)), None, 1.0, labels)
    truth = tmp_path / "t.yaml"
    truth.write_text(
        "rooms:\n"
        "  - {anchor: [20, 20], accept: [MAIN LAB], category: lab}\n"
        "  - {anchor: [70, 70], accept: [GALLEY], category: galley}\n"
        "  - {anchor: [50, 50], accept: [MESS], category: public}\n"
        "not_rooms:\n  - [70, 70]\n"
    )
    report = score(result, truth)
    assert (report.rooms_total, report.space_found, report.name_correct, report.category_correct) == (3, 1, 1, 1)
    assert report.not_rooms_correct == 1
