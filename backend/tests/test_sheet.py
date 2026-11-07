"""Finding stairs from their treads, and telling them apart from other parallel lines."""
from keel.extract import Segment
from keel.stairs import find_stairs

WIDTHS, SPACINGS = (11.0, 45.0), (3.4, 9.0)


def treads(x, y, count=10, spacing=5.0, length=18.0, width=0.48, rails=True):
    lines = [Segment(x + i * spacing, y, x + i * spacing, y + length, width) for i in range(count)]
    if rails:
        end = x + (count - 1) * spacing
        lines += [Segment(x, y, end, y, width), Segment(x, y + length, end, y + length, width)]
    return lines


def test_a_run_of_treads_is_a_stair_with_its_width_measured():
    stair = find_stairs(treads(100, 100), WIDTHS, SPACINGS)[0]
    assert stair.width == 18.0 and stair.treads == 10
    assert stair.box == (100, 100, 145, 118)


def test_horizontal_treads_also_count():
    lines = [Segment(100, 100 + i * 5.0, 118, 100 + i * 5.0, 0.48) for i in range(8)]
    lines += [Segment(100, 100, 100, 135, 0.48), Segment(118, 100, 118, 135, 0.48)]
    assert find_stairs(lines, WIDTHS, SPACINGS)[0].treads == 8


def test_too_few_treads_are_not_a_stair():
    assert find_stairs(treads(100, 100, count=4), WIDTHS, SPACINGS) == []


def test_treads_too_short_or_too_far_apart_are_not_a_stair():
    assert find_stairs(treads(100, 100, length=5.0), WIDTHS, SPACINGS) == []
    assert find_stairs(treads(100, 100, spacing=30.0), WIDTHS, SPACINGS) == []


def test_both_edges_of_a_tread_give_one_stair():
    doubled = treads(100, 100) + treads(100.1, 100)
    assert len(find_stairs(doubled, WIDTHS, (0.05, 9.0))) == 1


def test_two_flights_stay_separate():
    assert len(find_stairs(treads(100, 100) + treads(300, 100), WIDTHS, SPACINGS)) == 2


def test_parallel_lines_without_side_rails_are_not_a_stair():
    assert find_stairs(treads(100, 100, rails=False), WIDTHS, SPACINGS) == []
