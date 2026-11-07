import math
import random

import pytest

from keel.doors import (
    chain_curves,
    circle_from_points,
    dist,
    doors_from_arcs,
    find_door_arcs,
    fit_arc,
)
from keel.extract import Curve, Segment, bezier_to_points

KAPPA = 0.5523


def quarter_arc(cx, cy, r, a0_deg, width=0.36):
    """One Bezier quarter circle starting at a0 and sweeping +90 degrees."""
    a0 = math.radians(a0_deg)
    a1 = a0 + math.pi / 2
    p0 = (cx + r * math.cos(a0), cy + r * math.sin(a0))
    p3 = (cx + r * math.cos(a1), cy + r * math.sin(a1))
    p1 = (p0[0] - KAPPA * r * math.sin(a0), p0[1] + KAPPA * r * math.cos(a0))
    p2 = (p3[0] + KAPPA * r * math.sin(a1), p3[1] - KAPPA * r * math.cos(a1))
    return Curve(p0, p1, p2, p3, width)


def test_circle_from_points():
    center, radius = circle_from_points((1, 0), (0, 1), (-1, 0))
    assert center == pytest.approx((0, 0), abs=1e-9)
    assert radius == pytest.approx(1)
    assert circle_from_points((0, 0), (1, 1), (2, 2)) is None


def test_fit_arc_quarter_circle():
    chain = chain_curves([quarter_arc(10, 10, 5, 0)])[0]
    arc = fit_arc(chain)
    assert arc.radius == pytest.approx(5, abs=0.02)
    assert arc.sweep_deg == pytest.approx(90, abs=1)


def test_chain_joins_split_arc():
    half1 = quarter_arc(0, 0, 10, 0)
    half2 = quarter_arc(0, 0, 10, 90)
    chains = chain_curves([half1, half2])
    assert len(chains) == 1
    assert fit_arc(chains[0]).sweep_deg == pytest.approx(180, abs=2)


def test_find_door_arcs_filters_by_radius():
    curves = [quarter_arc(0, 0, 11, 0), quarter_arc(100, 0, 1, 0), quarter_arc(200, 0, 40, 0)]
    arcs = find_door_arcs(curves, 6, 16)
    assert [round(a.radius) for a in arcs] == [11]


def door_scene():
    """Hinge at (0,0) in a horizontal wall. Door closes along +x, opens along +y."""
    arc = fit_arc(chain_curves([quarter_arc(0, 0, 10, 0)])[0])
    segments = [
        Segment(0, 0, 10, 0),  # closed panel
        Segment(0, 0, 0, 10),  # open leaf
        Segment(11, 0, 60, 0),  # wall beyond latch
        Segment(-40, 0, -0.5, 0),  # wall behind hinge
    ]
    return arc, segments


def test_door_closes_along_the_wall():
    arc, segments = door_scene()
    doors, unresolved = doors_from_arcs([arc], segments)
    assert unresolved == []
    assert doors[0].hinge == pytest.approx((0, 0), abs=0.05)
    assert doors[0].latch == pytest.approx((10, 0), abs=0.1)
    assert doors[0].leaf_tip == pytest.approx((0, 10), abs=0.1)


def test_door_with_wall_on_both_axes_is_flagged_not_trusted():
    arc, segments = door_scene()
    segments = [s for s in segments if s.x0 >= 0]  # no wall behind the hinge
    segments.append(Segment(0, 11, 0, 30))  # bulkhead continuing along the open direction
    doors, _ = doors_from_arcs([arc], segments)
    assert doors[0].direction_confident is False


def test_clear_door_is_confident():
    arc, segments = door_scene()
    doors, _ = doors_from_arcs([arc], segments)
    assert doors[0].direction_confident is True


def test_arc_without_wall_is_unresolved_not_a_door():
    arc = fit_arc(chain_curves([quarter_arc(0, 0, 10, 0)])[0])
    segments = [Segment(0, 0, 10, 0), Segment(0, 0, 0, 10)]  # crane arm, no wall around it
    doors, unresolved = doors_from_arcs([arc], segments)
    assert doors == []
    assert unresolved == [arc]


def _slow_chain_curves(curves, join_tol=0.05):
    """The original search, kept to prove the faster one builds identical chains."""
    remaining = list(curves)
    chains = []
    while remaining:
        chain = bezier_to_points(remaining.pop())
        extended = True
        while extended:
            extended = False
            for i, c in enumerate(remaining):
                pts = bezier_to_points(c)
                if dist(chain[-1], pts[0]) < join_tol:
                    chain = chain + pts[1:]
                elif dist(chain[-1], pts[-1]) < join_tol:
                    chain = chain + pts[-2::-1]
                elif dist(chain[0], pts[-1]) < join_tol:
                    chain = pts[:-1] + chain
                elif dist(chain[0], pts[0]) < join_tol:
                    chain = pts[:0:-1] + chain
                else:
                    continue
                remaining.pop(i)
                extended = True
                break
        chains.append(chain)
    return chains


@pytest.mark.parametrize("seed", range(20))
def test_chain_curves_matches_the_original_search(seed):
    """End points land on a small lattice with jitter around the join tolerance, so branches,
    loops and near misses are all common."""
    rng = random.Random(seed)
    point = lambda: (rng.randrange(6) * 2 + rng.uniform(-0.03, 0.03), rng.randrange(6) * 2 + rng.uniform(-0.03, 0.03))
    curves = [Curve(point(), point(), point(), point()) for _ in range(rng.randrange(60, 200))]
    assert chain_curves(curves) == _slow_chain_curves(curves)


def test_chain_curves_handles_no_curves():
    assert chain_curves([]) == []
