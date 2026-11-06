import pytest
from shapely.geometry import Polygon, box

from keel.geometry import clear_width, dead_end_length, inscribed_diameter, side_of_line, without_thin_obstacles


def corridor(length=10000, width=1200):
    return box(0, 0, length, width)


def test_clear_width_of_straight_corridor():
    result = clear_width(corridor(), [(0, 600), (10000, 600)])
    assert result.width_mm == pytest.approx(1200, abs=4)


def test_clear_width_finds_the_pinch_and_where_it_is():
    narrowed = corridor().difference(box(4900, 0, 5100, 400))
    result = clear_width(narrowed, [(0, 600), (10000, 600)])
    assert result.width_mm == pytest.approx(800, abs=4)
    assert result.location[0] == pytest.approx(5000, abs=250)


def test_clear_width_ignores_thin_door_tick():
    with_tick = corridor().difference(box(5000, 0, 5040, 300))
    assert clear_width(with_tick, [(0, 600), (10000, 600)]).width_mm == pytest.approx(1200, abs=4)


def test_clear_width_needs_two_terminals():
    with pytest.raises(ValueError):
        clear_width(corridor(), [(0, 600)])


def test_thick_obstacle_is_not_ignored():
    with_column = corridor().difference(box(5000, 0, 5300, 500))
    assert clear_width(with_column, [(0, 600), (10000, 600)]).width_mm == pytest.approx(700, abs=4)


def test_inscribed_diameter_of_rectangle_is_short_side():
    diameter, _ = inscribed_diameter(box(0, 0, 4000, 1000))
    assert diameter == pytest.approx(1000, abs=3)


def test_closing_keeps_area_of_clean_room():
    room = box(0, 0, 2000, 2000)
    assert without_thin_obstacles(room).area == pytest.approx(room.area, rel=0.001)


def test_no_dead_end_between_two_exits():
    result = dead_end_length(corridor(), [(0, 600), (10000, 600)])
    assert result.length_mm == 0


def test_spur_counts_as_dead_end():
    t_shape = corridor(10000, 1000).union(box(4500, 1000, 5500, 9000))
    result = dead_end_length(t_shape, [(0, 500), (10000, 500)])
    # About 8.5 m walked into the spur, less the 1 m local width.
    assert result.length_mm == pytest.approx(7500, abs=400)


def test_recess_no_deeper_than_its_width_is_not_a_dead_end():
    with_recess = corridor(10000, 1000).union(box(4500, 1000, 5500, 1800))
    assert dead_end_length(with_recess, [(0, 500), (10000, 500)]).length_mm <= 400


def test_one_exit_makes_whole_corridor_a_dead_end():
    result = dead_end_length(corridor(10000, 1000), [(0, 500)])
    assert result.length_mm == pytest.approx(9000, abs=300)


def test_side_of_line():
    assert side_of_line((0, 0), (10, 0), (5, 5)) > 0
    assert side_of_line((0, 0), (10, 0), (5, -5)) < 0
