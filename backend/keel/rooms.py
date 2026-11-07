"""Rooms: the free floor area around each leader dot.

The drawing's lines do not form clean closed polygons, because furniture, door hardware
and leader lines all cross them. So we subtract instead of polygonizing:

    free space = plan region - (walls + closed door openings)

Each connected piece of free space is a cell. A room is the cell holding its label's dot.
Walls are selected by the drawing's own line weights. Leader lines and door leaves are
removed first because they cross or block floor that is really open.
"""
from __future__ import annotations

import cv2
import numpy as np

from dataclasses import dataclass

from shapely import STRtree
from shapely.geometry import LineString, MultiLineString, Point as ShapelyPoint, Polygon, box

from keel.doors import Arc, DetectedDoor, dist
from keel.extract import Curve, Fill, Point, Segment, bezier_to_points

# Line weights (pt) the RCRV drawings use for structure, joinery and bathroom modules.
WALL_WIDTHS = (0.24, 0.27, 0.36, 0.48, 0.54)
Region = tuple[float, float, float, float]


@dataclass(frozen=True)
class LeaderDot:
    x: float
    y: float
    radius: float = 1.9

    @property
    def point(self) -> Point:
        return (self.x, self.y)


def detect_leader_dots(
    fills: list[Fill],
    region: Region | None = None,
    min_pieces: int = 12,
    diameter_range: tuple[float, float] = (0.7, 4.5),
    segments: list[Segment] | None = None,
) -> list[LeaderDot]:
    """Leader dots are round, hatched from many small wedge fills. Cluster the wedges.

    The drawing uses two dot sizes. If segments are given, a dot counts only when a leader
    line actually ends at it, which rejects other small round symbols.
    """
    wedges = [
        f
        for f in fills
        if (f.x1 - f.x0) <= 2.5
        and (f.y1 - f.y0) <= 2.5
        and max(f.x1 - f.x0, f.y1 - f.y0) >= 0.3
        and (region is None or (region[0] <= f.x0 <= region[2] and region[1] <= f.y0 <= region[3]))
    ]
    clusters: list[list[Fill]] = []
    boxes: list[list[float]] = []
    for w in wedges:
        for i, b in enumerate(boxes):
            if w.x0 <= b[2] + 0.2 and w.x1 >= b[0] - 0.2 and w.y0 <= b[3] + 0.2 and w.y1 >= b[1] - 0.2:
                clusters[i].append(w)
                b[0], b[1] = min(b[0], w.x0), min(b[1], w.y0)
                b[2], b[3] = max(b[2], w.x1), max(b[3], w.y1)
                break
        else:
            clusters.append([w])
            boxes.append([w.x0, w.y0, w.x1, w.y1])

    dots = []
    for cluster, b in zip(clusters, boxes):
        width, height = b[2] - b[0], b[3] - b[1]
        round_enough = abs(width - height) <= 0.2 * max(width, height)
        # A solid dot is one fill. It is only accepted with a leader line ending at it.
        enough_pieces = len(cluster) >= min_pieces or segments is not None
        if (
            enough_pieces
            and (len(cluster) >= min_pieces or max(width, height) <= 2.5)
            and round_enough
            and diameter_range[0] <= max(width, height) <= diameter_range[1]
        ):
            dots.append(LeaderDot((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, max(width, height) / 2))
    if segments is not None:
        dots = [d for d in dots if find_leader_lines(segments, [d])]
    return dots


def find_leader_lines(
    segments: list[Segment], dots: list[LeaderDot], margin: float = 0.3, min_length: float = 0.7
) -> set[Segment]:
    """Straight lines ending in a leader dot. These cross rooms and must not count as walls."""
    leaders = set()
    for s in segments:
        if s.length < min_length:
            continue
        for d in dots:
            tol = d.radius + margin
            if dist((s.x0, s.y0), d.point) <= tol or dist((s.x1, s.y1), d.point) <= tol:
                leaders.add(s)
                break
    return leaders


def _near_line(p: Point, a: Point, b: Point, tol: float) -> bool:
    """True if p lies within tol of the segment a-b."""
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return dist(p, a) <= tol
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / length2))
    return dist(p, (ax + t * dx, ay + t * dy)) <= tol


def door_furniture_segments(
    segments: list[Segment], doors: list[DetectedDoor], leaf_tol: float = 1.2
) -> set[Segment]:
    """Door leaf lines and the centre tick mark. They are symbols, not floor obstructions."""
    symbols = set()
    for door in doors:
        reach = door.radius_pt * 1.15
        center_mid = ((door.hinge[0] + door.latch[0]) / 2, (door.hinge[1] + door.latch[1]) / 2)
        for s in segments:
            a, b = (s.x0, s.y0), (s.x1, s.y1)
            if dist(a, door.hinge) > reach * 1.2 and dist(b, door.hinge) > reach * 1.2:
                continue
            # Leaf: both ends lie along the hinge-to-open-tip line.
            if _near_line(a, door.hinge, door.leaf_tip, leaf_tol) and _near_line(
                b, door.hinge, door.leaf_tip, leaf_tol
            ):
                symbols.add(s)
            # Centre tick: a short line crossing the middle of the opening.
            elif s.length < 0.8 * door.radius_pt and _near_line(center_mid, a, b, 0.8):
                symbols.add(s)
    return symbols


def door_arc_curves(curves: list[Curve], arcs: list[Arc], tol: float = 0.4) -> set[Curve]:
    """Bezier pieces that belong to a door swing arc. These must not act as walls."""
    drawn = set()
    for c in curves:
        for arc in arcs:
            r0, r1 = dist(c.p0, arc.center), dist(c.p3, arc.center)
            if abs(r0 - arc.radius) <= tol and abs(r1 - arc.radius) <= tol:
                drawn.add(c)
                break
    return drawn


def door_closure_lines(
    a: Point, b: Point, overshoot: float = 1.5, cap_half: float = 1.0
) -> list[LineString]:
    """Seal a door opening: the chord, extended past both jambs, with a cap at each end.

    Door lines stop just short of double-line walls, leaving a gap into the wall cavity.
    The caps close that cavity, so two rooms cannot connect through it.
    """
    length = dist(a, b)
    if length == 0:
        return []
    ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
    start = (a[0] - ux * overshoot, a[1] - uy * overshoot)
    end = (b[0] + ux * overshoot, b[1] + uy * overshoot)
    nx, ny = -uy * cap_half, ux * cap_half
    return [
        LineString([start, end]),
        LineString([(start[0] - nx, start[1] - ny), (start[0] + nx, start[1] + ny)]),
        LineString([(end[0] - nx, end[1] - ny), (end[0] + nx, end[1] + ny)]),
    ]


def build_wall_lines(
    segments: list[Segment],
    curves: list[Curve],
    doors: list[DetectedDoor],
    leaders: set[Segment],
    arcs: list[Arc],
    wall_widths: tuple[float, ...] = WALL_WIDTHS,
) -> list[LineString]:
    """Everything that blocks floor area, as line geometry."""
    symbols = door_furniture_segments(segments, doors)
    arc_curves = door_arc_curves(curves, arcs)

    def is_wall_width(width: float) -> bool:
        return any(abs(width - w) < 0.005 for w in wall_widths)

    lines = [
        LineString([(s.x0, s.y0), (s.x1, s.y1)])
        for s in segments
        if s.length > 0.05
        and is_wall_width(s.width)
        and not s.gray
        and s not in leaders
        and s not in symbols
    ]
    for c in curves:
        if is_wall_width(c.width) and not c.gray and c not in arc_curves:
            lines.append(LineString(bezier_to_points(c, steps=6)))
    # A closed door is a barrier between rooms.
    for door in doors:
        lines.extend(door_closure_lines(door.hinge, door.latch))
        if not door.direction_confident:
            # Direction unknown: close both candidates so rooms cannot leak into each other.
            lines.extend(door_closure_lines(door.hinge, door.leaf_tip))
    return lines


def free_cells_on_grid(region: Region, wall_lines: list[LineString], px_per_pt: float = 4.0) -> list[Polygon]:
    """The same result for very detailed drawings, by drawing the walls on a grid.

    Exact geometry takes many minutes above tens of thousands of lines. A quarter point is
    well inside the measuring tolerance, which is added for this reason.
    """
    width = int((region[2] - region[0]) * px_per_pt) + 1
    height = int((region[3] - region[1]) * px_per_pt) + 1
    ink = np.zeros((height, width), np.uint8)
    for line in wall_lines:
        points = ((np.asarray(line.coords) - (region[0], region[1])) * px_per_pt).round().astype(np.int32)
        cv2.polylines(ink, [points], False, 1, 2)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(1 - ink, connectivity=4)
    cells = []
    for number in range(1, count):
        x, y, w, h, area = stats[number]
        if area < 16:
            continue
        mask = (labels[y : y + h, x : x + w] == number).astype(np.uint8)
        contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        to_pt = lambda c: [((px + x) / px_per_pt + region[0], (py + y) / px_per_pt + region[1]) for px, py in c.reshape(-1, 2)]
        for index, contour in enumerate(contours):
            if hierarchy[0][index][3] != -1 or len(contour) < 3:
                continue
            holes = [
                to_pt(inner)
                for j, inner in enumerate(contours)
                if hierarchy[0][j][3] == index and len(inner) >= 3
            ]
            polygon = Polygon(to_pt(contour), holes)
            if not polygon.is_valid:
                polygon = polygon.buffer(0)
            cells.extend(p for p in getattr(polygon, "geoms", [polygon]) if p.geom_type == "Polygon" and not p.is_empty)
    return cells


def free_cells(region: Region, wall_lines: list[LineString], half_stroke: float = 0.18) -> list[Polygon]:
    """Connected pieces of floor. half_stroke places boundaries at the ink edge of the walls."""
    ink = MultiLineString(wall_lines).buffer(half_stroke, quad_segs=2)
    free = box(*region).difference(ink)
    if free.geom_type == "Polygon":
        return [free]
    return [g for g in free.geoms if g.geom_type == "Polygon"]


def cell_at(cells: list[Polygon], tree: STRtree, point: Point) -> Polygon | None:
    """The free cell containing this point, or None if the point is on ink."""
    shapely_point = ShapelyPoint(point)
    for index in tree.query(shapely_point):
        if cells[int(index)].contains(shapely_point):
            return cells[int(index)]
    return None


def cell_near(
    cells: list[Polygon], tree: STRtree, point: Point, search_radius: float = 3.0
) -> Polygon | None:
    """Like cell_at, but tolerates a point sitting on ink: the largest cell within reach."""
    exact = cell_at(cells, tree, point)
    if exact is not None:
        return exact
    disk = ShapelyPoint(point).buffer(search_radius)
    candidates = [cells[int(i)] for i in tree.query(disk) if cells[int(i)].intersects(disk)]
    return max(candidates, key=lambda c: c.area) if candidates else None


__all__ = [
    "LeaderDot",
    "WALL_WIDTHS",
    "build_wall_lines",
    "cell_at",
    "cell_near",
    "detect_leader_dots",
    "door_arc_curves",
    "door_closure_lines",
    "door_furniture_segments",
    "find_leader_lines",
    "free_cells",
]
