from PIL import Image

from keel.extract import Segment
from keel.labels import (
    LabelBlock,
    TextItem,
    _drop_overlaps,
    block_has_leader,
    group_blocks,
    leader_tail_strokes,
    parse_compartment,
    place_labels,
    render_text_layer,
    trace_leader_tails,
)
from keel.rooms import LeaderDot


def test_parse_compartment_restores_dashes():
    assert parse_compartment("01362") == "01-36-2"
    assert parse_compartment("1-33-0") == "1-33-0"
    assert parse_compartment("SCIENCE") is None
    assert parse_compartment("01-(-4)-0") is None


def block(name, x0, y0, x1, y1, compartment=None):
    return LabelBlock(name, compartment, ((x0 + x1) / 2, (y0 + y1) / 2), x0, y0, x1, y1, 0.99)


def test_group_blocks_joins_name_and_number():
    items = [TextItem("SCIENCE", 10, 10, 40, 16, 0.9), TextItem("01362", 12, 17, 38, 22, 0.8)]
    result = group_blocks(items)
    assert len(result) == 1
    assert result[0].name == "SCIENCE"
    assert result[0].compartment == "01-36-2"
    assert result[0].confidence == 0.8


def test_short_piece_at_dot_is_refined_through_the_centre():
    dot = LeaderDot(100, 100, 1.6)
    # A 1.7 pt piece whose direction is slightly off, then the real long leader.
    segments = [Segment(100.1, 98.4, 100.0, 96.7, 0.18), Segment(100.0, 90.0, 100.0, 20.0, 0.18)]
    ends = trace_leader_tails(dot, segments)[0]
    assert ends[0][1] == 20.0


def test_leader_crosses_breaks_and_turns_into_an_elbow():
    dot = LeaderDot(100, 100, 1.6)
    segments = [
        Segment(100, 98.5, 100, 70, 0.18),
        Segment(100, 60, 100, 30, 0.18),  # broken where it crosses a wall
        Segment(100, 30, 108, 30, 0.18),  # elbow towards the text
    ]
    ends = trace_leader_tails(dot, segments)[0]
    assert ends[0] == (108, 30)


def test_place_labels_follows_the_leader_past_nearer_text():
    dot = LeaderDot(100, 100, 1.6)
    segments = [Segment(100, 98.5, 100, 30, 0.18), Segment(100, 30, 108, 30, 0.18)]
    room_text = block("WRONG", 105, 92, 130, 98)
    far_text = block("RIGHT", 109, 27, 135, 33)
    placed = place_labels([room_text, far_text], [dot], segments)
    by_name = {p.block.name: p for p in placed}
    assert by_name["RIGHT"].via == "leader"
    assert by_name["RIGHT"].anchor == (100, 100)
    assert by_name["WRONG"].via == "in_room"


def test_each_dot_and_block_is_used_once():
    dots = [LeaderDot(100, 100, 1.6), LeaderDot(200, 100, 1.6)]
    segments = [Segment(100, 98.5, 100, 40, 0.18), Segment(200, 98.5, 200, 40, 0.18)]
    placed = place_labels([block("A", 90, 30, 110, 39), block("B", 190, 30, 210, 39)], dots, segments)
    assert {p.block.name: p.anchor[0] for p in placed} == {"A": 100, "B": 200}


def test_block_with_a_line_at_its_edge_has_a_leader():
    label = block("CG LKR", 100, 100, 130, 110)
    assert block_has_leader(label, [Segment(131, 105, 160, 150, 0.18)])
    assert not block_has_leader(label, [Segment(200, 105, 260, 105, 0.18)])


def test_leader_tails_are_found_and_left_out_of_the_text_image():
    dot = LeaderDot(50, 50, 1.6)
    tail = Segment(50, 20, 57, 20, 0.18)
    segments = [Segment(50, 48.5, 50, 20, 0.18), tail]
    assert tail in leader_tail_strokes([dot], segments)
    drawn = render_text_layer([tail], [], (0, 0, 100, 100), scale=2)
    hidden = render_text_layer([tail], [], (0, 0, 100, 100), scale=2, exclude={tail})
    assert drawn.getextrema()[0] == 0
    assert hidden.getextrema()[0] == 255
    assert isinstance(hidden, Image.Image)


def test_overlapping_tile_readings_keep_the_better_copy():
    items = [TextItem("MAIN LA", 10, 10, 40, 16, 0.9), TextItem("MAIN LAB", 10, 10, 44, 16, 0.95), TextItem("GALLEY", 100, 10, 130, 16, 0.9)]
    assert sorted(i.text for i in _drop_overlaps(items)) == ["GALLEY", "MAIN LAB"]
