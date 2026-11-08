"""Deterministic measurements on floor polygons. All inputs and outputs are in millimetres."""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

import shapely
from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points
from shapely.prepared import prep

PointMM = tuple[float, float]

# Obstacles thinner than twice this (door ticks, jamb caps, trim) are not treated as
# narrowing a passage. Real obstructions such as furniture are much thicker.
THIN_OBSTACLE_RADIUS_MM = 55.0


def without_thin_obstacles(polygon: Polygon, radius_mm: float = THIN_OBSTACLE_RADIUS_MM) -> BaseGeometry:
    """Morphological closing: fills in slivers of wall symbol thinner than 2 * radius."""
    return polygon.buffer(radius_mm, quad_segs=4).buffer(-radius_mm, quad_segs=4)


def _parts(geometry: BaseGeometry) -> list[Polygon]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    return [g for g in getattr(geometry, "geoms", []) if isinstance(g, Polygon)]


def inscribed_diameter(polygon: BaseGeometry) -> tuple[float, PointMM]:
    """Diameter and centre of the largest circle fitting inside the polygon."""
    parts = _parts(polygon)
    if not parts:
        return 0.0, (0.0, 0.0)
    largest = max(parts, key=lambda p: p.area)
    line = shapely.maximum_inscribed_circle(largest, tolerance=1.0)
    start, end = line.coords[0], line.coords[1]
    return 2 * math.dist(start, end), (start[0], start[1])


@dataclass(frozen=True)
class ClearWidth:
    width_mm: float
    location: PointMM  # centre of the narrowest passage
    limited_by_terminals: bool  # True if a terminal disconnects before the passage splits


def _terminal_part(parts: list[Polygon], terminal: PointMM, reach_mm: float) -> int | None:
    """Index of the part this terminal can reach, or None."""
    point = Point(terminal)
    best, best_distance = None, reach_mm
    for i, part in enumerate(parts):
        distance = part.distance(point)
        if distance <= best_distance:
            best, best_distance = i, distance
    return best


def _terminals_connected(eroded: BaseGeometry, terminals: list[PointMM], width: float, reach_extra: float) -> bool:
    parts = _parts(eroded)
    if not parts:
        return False
    reach = width / 2 + reach_extra
    indices = {_terminal_part(parts, t, reach) for t in terminals}
    return None not in indices and len(indices) == 1


def clear_width(
    polygon: Polygon,
    terminals: list[PointMM],
    resolution_mm: float = 2.0,
    reach_extra_mm: float = 400.0,
) -> ClearWidth:
    """Widest object that can travel between all terminals: binary search on erosion.

    A corridor passes width w if eroding it by w/2 still leaves the terminals connected.
    Thin door symbols are ignored first. reach_extra lets a terminal sit in a door recess.
    """
    if len(terminals) < 2:
        raise ValueError("clear_width needs at least two terminals")
    floor = without_thin_obstacles(polygon)
    low, high = 0.0, inscribed_diameter(floor)[0] + resolution_mm
    if not _terminals_connected(floor, terminals, 0.0, reach_extra_mm):
        return ClearWidth(0.0, terminals[0], True)
    while high - low > resolution_mm:
        middle = (low + high) / 2
        eroded = floor.buffer(-middle / 2, quad_segs=4)
        if _terminals_connected(eroded, terminals, middle, reach_extra_mm):
            low = middle
        else:
            high = middle

    # The passage is just about to split at `high`: the pinch lies between the parts.
    parts = _parts(floor.buffer(-high / 2, quad_segs=4))
    reach = high / 2 + reach_extra_mm
    held = {_terminal_part(parts, t, reach) for t in terminals}
    usable = [parts[i] for i in held if i is not None]
    if len(usable) >= 2:
        best_pair, best_gap = None, math.inf
        for i, a in enumerate(usable):
            for b in usable[i + 1 :]:
                gap = a.distance(b)
                if gap < best_gap:
                    best_gap, best_pair = gap, (a, b)
        p, q = nearest_points(*best_pair)
        return ClearWidth(low, ((p.x + q.x) / 2, (p.y + q.y) / 2), False)

    # A terminal dropped out first, so its own recess sets the limit.
    missing = [t for t, part in zip(terminals, [_terminal_part(parts, t, reach) for t in terminals]) if part is None]
    return ClearWidth(low, missing[0] if missing else terminals[0], True)


@dataclass(frozen=True)
class DeadEnd:
    length_mm: float
    tip: PointMM
    route_mm: float


def dead_end_length(
    polygon: Polygon, exits: list[PointMM], cell_mm: float = 100.0, recess_allowance: bool = True
) -> DeadEnd:
    """Longest walk from the through-route between exits to the far end of the corridor.

    Grid geodesic distance. With one exit, the whole corridor counts as a dead end. A recess
    no deeper than its width is allowed by SOLAS II-2/13.3.1, so the local width is
    subtracted. The result is accurate to the grid size, which the caller adds as tolerance.
    """
    if not exits:
        raise ValueError("dead_end_length needs at least one exit")
    floor = without_thin_obstacles(polygon)
    minx, miny, maxx, maxy = floor.bounds
    nx, ny = int((maxx - minx) / cell_mm) + 2, int((maxy - miny) / cell_mm) + 2
    inside = prep(floor)
    free = [[inside.contains(Point(minx + i * cell_mm, miny + j * cell_mm)) for j in range(ny)] for i in range(nx)]

    def nearest_cell(p: PointMM) -> tuple[int, int] | None:
        ci, cj = round((p[0] - minx) / cell_mm), round((p[1] - miny) / cell_mm)
        for radius in range(0, 20):
            best, best_distance = None, math.inf
            for i in range(ci - radius, ci + radius + 1):
                for j in range(cj - radius, cj + radius + 1):
                    if 0 <= i < nx and 0 <= j < ny and free[i][j]:
                        d = (i - ci) ** 2 + (j - cj) ** 2
                        if d < best_distance:
                            best, best_distance = (i, j), d
            if best is not None:
                return best
        return None

    def bfs(sources: list[tuple[int, int]]) -> dict[tuple[int, int], int]:
        distance = {s: 0 for s in sources}
        queue = deque(sources)
        while queue:
            ci, cj = queue.popleft()
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (ci + di, cj + dj)
                if 0 <= n[0] < nx and 0 <= n[1] < ny and free[n[0]][n[1]] and n not in distance:
                    distance[n] = distance[(ci, cj)] + 1
                    queue.append(n)
        return distance

    exit_cells = [c for c in (nearest_cell(e) for e in exits) if c is not None]
    if not exit_cells:
        raise ValueError("exits are not inside the corridor")

    # Through-route: shortest path between the two exits that are farthest apart.
    route_cells: list[tuple[int, int]] = []
    if len(exit_cells) >= 2:
        best_pair, best_steps = None, -1
        for i, a in enumerate(exit_cells):
            distance = bfs([a])
            for b in exit_cells[i + 1 :]:
                if distance.get(b, -1) > best_steps:
                    best_steps, best_pair = distance[b], (a, b)
        if best_pair is not None:
            a, b = best_pair
            distance = bfs([a])
            current = b
            route_cells = [current]
            while current != a:
                ci, cj = current
                for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    n = (ci + di, cj + dj)
                    if distance.get(n, 1 << 30) == distance[current] - 1:
                        current = n
                        break
                route_cells.append(current)
    sources = route_cells or exit_cells
    distance = bfs(sources)
    tip_cell = max(distance, key=distance.get)
    tip = (minx + tip_cell[0] * cell_mm, miny + tip_cell[1] * cell_mm)
    walked = distance[tip_cell] * cell_mm
    if not recess_allowance:
        # The plain walk to the farthest point, such as travel distance to a room's door.
        return DeadEnd(walked, tip, len(route_cells) * cell_mm)
    local_width, _ = inscribed_diameter(floor.intersection(Point(tip).buffer(2000.0)))
    return DeadEnd(max(0.0, walked - local_width), tip, len(route_cells) * cell_mm)


def side_of_line(a: PointMM, b: PointMM, p: PointMM) -> float:
    """Signed area test: positive on one side of a->b, negative on the other."""
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
