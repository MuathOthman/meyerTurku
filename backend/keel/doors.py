"""Door detection: quarter-circle swing arc plus a leaf line from the arc centre.

A door is recognised geometrically, without any AI:
  1. chain Bezier pieces into arcs and fit a circle,
  2. keep door-sized arcs of 45-110 degrees (cabin door arcs are trimmed to about 52),
  3. require perpendicular leaf and closed directions from the arc centre (hinge),
  4. require wall continuing along the closed direction.

Hinge to latch is the door opening. The arc lies on the side the door swings towards.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from keel.extract import Curve, Point, Segment, bezier_to_points


@dataclass(frozen=True)
class Arc:
    center: Point
    radius: float
    start: Point
    end: Point
    sweep_deg: float
    mid: Point


@dataclass(frozen=True)
class DetectedDoor:
    hinge: Point
    latch: Point  # arc end in the closed position (lies on the wall line)
    leaf_tip: Point  # arc end in the open position (drawn leaf end)
    arc_mid: Point
    radius_pt: float
    sweep_deg: float
    direction_confident: bool = True


def dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def circle_from_points(a: Point, b: Point, c: Point) -> tuple[Point, float] | None:
    """Circumcircle of three points, or None if they are collinear."""
    d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
    if abs(d) < 1e-9:
        return None
    a2, b2, c2 = a[0] ** 2 + a[1] ** 2, b[0] ** 2 + b[1] ** 2, c[0] ** 2 + c[1] ** 2
    ux = (a2 * (b[1] - c[1]) + b2 * (c[1] - a[1]) + c2 * (a[1] - b[1])) / d
    uy = (a2 * (c[0] - b[0]) + b2 * (a[0] - c[0]) + c2 * (b[0] - a[0])) / d
    return (ux, uy), dist((ux, uy), a)


def chain_curves(curves: list[Curve], join_tol: float = 0.05) -> list[list[Point]]:
    """Join Bezier pieces whose end points touch into ordered polylines.

    A chain takes the first unused piece, in input order, that touches either of its ends.
    A grid of end points finds that piece without comparing against every curve.
    """
    points = [bezier_to_points(c) for c in curves]
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    cell = lambda p: (math.floor(p[0] / join_tol), math.floor(p[1] / join_tol))
    for index, pts in enumerate(points):
        grid[cell(pts[0])].append(index)
        if cell(pts[-1]) != cell(pts[0]):
            grid[cell(pts[-1])].append(index)

    used = [False] * len(points)

    def first_touching(*ends: Point) -> int | None:
        best = None
        for end in ends:
            cx, cy = cell(end)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for index in grid.get((cx + dx, cy + dy), ()):
                        if used[index] or (best is not None and index >= best):
                            continue
                        pts = points[index]
                        if dist(end, pts[0]) < join_tol or dist(end, pts[-1]) < join_tol:
                            best = index
        return best

    chains: list[list[Point]] = []
    for start in range(len(points) - 1, -1, -1):
        if used[start]:
            continue
        used[start] = True
        chain = points[start]
        while (index := first_touching(chain[-1], chain[0])) is not None:
            pts = points[index]
            used[index] = True
            if dist(chain[-1], pts[0]) < join_tol:
                chain = chain + pts[1:]
            elif dist(chain[-1], pts[-1]) < join_tol:
                chain = chain + pts[-2::-1]
            elif dist(chain[0], pts[-1]) < join_tol:
                chain = pts[:-1] + chain
            else:
                chain = pts[:0:-1] + chain
        chains.append(chain)
    return chains


def fit_arc(points: list[Point], max_residual_ratio: float = 0.03) -> Arc | None:
    """Fit a circle through a polyline. None if it is not a true circular arc."""
    if len(points) < 3:
        return None
    mid_point = points[len(points) // 2]
    circle = circle_from_points(points[0], mid_point, points[-1])
    if circle is None:
        return None
    center, radius = circle
    if radius <= 0:
        return None
    if any(abs(dist(p, center) - radius) > max_residual_ratio * radius for p in points):
        return None
    sweep = 0.0
    for p, q in zip(points, points[1:]):
        a1 = math.atan2(p[1] - center[1], p[0] - center[0])
        a2 = math.atan2(q[1] - center[1], q[0] - center[0])
        delta = (a2 - a1 + math.pi) % (2 * math.pi) - math.pi
        sweep += delta
    return Arc(center, radius, points[0], points[-1], abs(math.degrees(sweep)), mid_point)


def find_door_arcs(
    curves: list[Curve],
    min_radius_pt: float,
    max_radius_pt: float,
    sweep_range_deg: tuple[float, float] = (45.0, 110.0),
) -> list[Arc]:
    """Arcs with a door-sized radius and about a quarter-circle sweep."""
    arcs = []
    for chain in chain_curves(curves):
        arc = fit_arc(chain)
        if (
            arc is not None
            and min_radius_pt <= arc.radius <= max_radius_pt
            and sweep_range_deg[0] <= arc.sweep_deg <= sweep_range_deg[1]
        ):
            arcs.append(arc)
    return arcs


def find_polyline_door_arcs(
    segments: list[Segment],
    min_radius_pt: float,
    max_radius_pt: float,
    sweep_range_deg: tuple[float, float] = (45.0, 110.0),
    join_tol: float = 0.02,
    max_piece_pt: float = 6.0,
) -> tuple[list[Arc], set[Segment]]:
    """Some CAD exports draw arcs as many tiny straight lines. Join them, then fit a circle."""
    pieces = [s for s in segments if s.length < max_piece_pt]
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    cell = lambda p: (round(p[0] / join_tol), round(p[1] / join_tol))
    for index, s in enumerate(pieces):
        grid[cell((s.x0, s.y0))].append(index)
        grid[cell((s.x1, s.y1))].append(index)
    used = [False] * len(pieces)

    def next_piece(point: Point) -> tuple[int, Point] | None:
        cx, cy = cell(point)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for index in grid.get((cx + dx, cy + dy), ()):
                    if used[index]:
                        continue
                    s = pieces[index]
                    if dist((s.x0, s.y0), point) < join_tol:
                        return index, (s.x1, s.y1)
                    if dist((s.x1, s.y1), point) < join_tol:
                        return index, (s.x0, s.y0)
        return None

    arcs, members = [], set()
    for index, s in enumerate(pieces):
        if used[index]:
            continue
        used[index] = True
        chain, chosen = [(s.x0, s.y0), (s.x1, s.y1)], [s]
        for forward in (True, False):
            while (found := next_piece(chain[-1] if forward else chain[0])) is not None:
                used[found[0]] = True
                chosen.append(pieces[found[0]])
                if forward:
                    chain.append(found[1])
                else:
                    chain.insert(0, found[1])
        if len(chain) < 4:
            continue
        arc = fit_arc(chain)
        if (
            arc is not None
            and min_radius_pt <= arc.radius <= max_radius_pt
            and sweep_range_deg[0] <= arc.sweep_deg <= sweep_range_deg[1]
        ):
            arcs.append(arc)
            members.update(chosen)
    return arcs, members


def _radial_angles(
    center: Point, radius: float, segments: list[Segment], tol: float, min_ratio: float = 0.5
) -> list[tuple[float, float]]:
    """(angle, length) of straight lines starting at the centre and running outward."""
    found = []
    for s in segments:
        a, b = (s.x0, s.y0), (s.x1, s.y1)
        near, far = (a, b) if dist(a, center) <= dist(b, center) else (b, a)
        reach = dist(far, center)
        if dist(near, center) > tol or not min_ratio * radius <= reach <= 1.25 * radius:
            continue
        found.append((math.atan2(far[1] - center[1], far[0] - center[0]), reach))
    return found


def _angle_delta(a: float, b: float) -> float:
    """Signed smallest rotation from a to b, in radians."""
    return (b - a + math.pi) % (2 * math.pi) - math.pi


def _wall_extension(
    center: Point, angle: float, radius: float, walls: list[Segment], tol: float
) -> float:
    """Length of parallel wall along this direction that lies outside the door opening.

    A door sits in a wall, so its closed direction has wall continuing past the latch or
    behind the hinge. Only long, parallel lines count, so nearby clutter is ignored.
    """
    ux, uy = math.cos(angle), math.sin(angle)
    extension = 0.0
    for s in walls:
        if s.length < 0.3 * radius:
            continue
        cross = abs((s.x1 - s.x0) * uy - (s.y1 - s.y0) * ux) / s.length
        if cross > math.sin(math.radians(4.0)):
            continue
        offsets = []
        for px, py in ((s.x0, s.y0), (s.x1, s.y1)):
            dx, dy = px - center[0], py - center[1]
            if abs(dx * uy - dy * ux) > tol:
                break
            offsets.append(dx * ux + dy * uy)
        else:
            lo, hi = min(offsets), max(offsets)
            if lo <= 1.35 * radius and hi > 1.02 * radius:
                extension += min(hi, 4 * radius) - max(lo, 1.02 * radius)
            if hi >= -0.35 * radius and lo < -0.02 * radius:
                extension += min(hi, -0.02 * radius) - max(lo, -4 * radius)
    return extension


def _resolve_directions(
    arc: Arc,
    angles: list[float],
    wall_lines: list[Segment],
    perpendicular: float,
    wall_tol_pt: float,
    min_extension: float,
) -> tuple[float, float, bool] | None:
    """Pick (closed, open, confident) from candidate directions, or None if no evidence.

    Not confident means the open direction has substantial wall as well, for example a
    door resting against a bulkhead. Then the swing cannot be read reliably.
    """
    arc_angles = [
        math.atan2(p[1] - arc.center[1], p[0] - arc.center[0])
        for p in (arc.start, arc.end, arc.mid)
    ]
    best_score = 0.0
    best: tuple[float, float, bool] | None = None
    for i, first in enumerate(angles):
        for second in angles[i + 1 :]:
            delta = _angle_delta(first, second)
            if abs(abs(delta) - math.pi / 2) > perpendicular:
                continue
            # The whole arc must lie in the sector between the two directions.
            sign = 1 if delta > 0 else -1
            if not all(
                -perpendicular <= _angle_delta(first, a) * sign <= abs(delta) + perpendicular
                for a in arc_angles
            ):
                continue
            ext = {
                angle: _wall_extension(arc.center, angle, arc.radius, wall_lines, wall_tol_pt)
                for angle in (first, second)
            }
            for closed, opened in ((first, second), (second, first)):
                score = ext[closed] - ext[opened]
                if ext[closed] >= min_extension and score > best_score:
                    best_score = score
                    best = (closed, opened, ext[opened] <= 0.5 * ext[closed])
    return best


def doors_from_arcs(
    arcs: list[Arc],
    segments: list[Segment],
    walls: list[Segment] | None = None,
    hinge_tol_pt: float = 1.5,
    perpendicular_tol_deg: float = 14.0,
    wall_tol_pt: float = 1.2,
    min_wall_extension_ratio: float = 0.25,
) -> tuple[list[DetectedDoor], list[Arc]]:
    """Turn swing arcs into doors. Returns (doors, unresolved arcs).

    Arcs may be trimmed, so arc ends are not trusted alone. The door is the pair of
    perpendicular directions around the arc: open leaf and closed position. Arcs without
    that evidence are returned as unresolved for engineer review, never guessed.
    """
    wall_lines = walls if walls is not None else segments
    perpendicular = math.radians(perpendicular_tol_deg)
    doors: list[DetectedDoor] = []
    unresolved: list[Arc] = []
    for arc in arcs:
        margin = arc.radius * 1.3
        nearby = [
            s
            for s in segments
            if min(dist((s.x0, s.y0), arc.center), dist((s.x1, s.y1), arc.center)) <= margin
        ]
        angles = [angle for angle, _ in _radial_angles(arc.center, arc.radius, nearby, hinge_tol_pt)]
        if not angles:
            unresolved.append(arc)
            continue
        if arc.sweep_deg >= 75:
            angles.append(math.atan2(arc.start[1] - arc.center[1], arc.start[0] - arc.center[0]))
            angles.append(math.atan2(arc.end[1] - arc.center[1], arc.end[0] - arc.center[0]))
        resolved = _resolve_directions(
            arc, angles, wall_lines, perpendicular, wall_tol_pt, min_wall_extension_ratio * arc.radius
        )
        if resolved is None:
            unresolved.append(arc)
            continue
        closed, opened, confident = resolved
        latch = (
            arc.center[0] + arc.radius * math.cos(closed),
            arc.center[1] + arc.radius * math.sin(closed),
        )
        tip = (
            arc.center[0] + arc.radius * math.cos(opened),
            arc.center[1] + arc.radius * math.sin(opened),
        )
        doors.append(
            DetectedDoor(arc.center, latch, tip, arc.mid, arc.radius, arc.sweep_deg, confident)
        )
    return doors, unresolved
