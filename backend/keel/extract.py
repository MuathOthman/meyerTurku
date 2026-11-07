"""PDF -> raw vector primitives, in displayed page coordinates (points).

PyMuPDF returns drawing coordinates in the unrotated page space. The RCRV sheets
are stored with /Rotate 90, so every point goes through the page rotation matrix.
All later code can then treat "x right, y down" as what the reader sees.

No interpretation happens here: no walls, doors or rooms, only what the PDF says.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import pymupdf

Point = tuple[float, float]


@dataclass(frozen=True)
class Segment:
    x0: float
    y0: float
    x1: float
    y1: float
    width: float = 0.0
    gray: bool = False

    @cached_property
    def length(self) -> float:
        return math.hypot(self.x1 - self.x0, self.y1 - self.y0)

    @property
    def midpoint(self) -> Point:
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)


@dataclass(frozen=True)
class Curve:
    """One cubic Bezier segment."""

    p0: Point
    p1: Point
    p2: Point
    p3: Point
    width: float = 0.0
    path_id: int = -1
    gray: bool = False


@dataclass(frozen=True)
class Fill:
    """Bounding box of one solid filled path. Leader dots are built from these."""

    x0: float
    y0: float
    x1: float
    y1: float


@dataclass
class Primitives:
    page_index: int
    page_width: float
    page_height: float
    segments: list[Segment]
    curves: list[Curve]
    fills: list[Fill] = field(default_factory=list)


def bezier_to_points(curve: Curve, steps: int = 8) -> list[Point]:
    """Flatten a cubic Bezier to a polyline, including both end points."""
    pts = []
    for i in range(steps + 1):
        t = i / steps
        m = 1 - t
        a, b, c = m * m * m, 3 * m * m * t, 3 * m * t * t
        d = t * t * t
        pts.append(
            (
                a * curve.p0[0] + b * curve.p1[0] + c * curve.p2[0] + d * curve.p3[0],
                a * curve.p0[1] + b * curve.p1[1] + c * curve.p2[1] + d * curve.p3[1],
            )
        )
    return pts


def extract_page(page: pymupdf.Page) -> Primitives:
    """Read the line, rectangle, quad and curve primitives of one page."""
    matrix = page.rotation_matrix
    segments: list[Segment] = []
    curves: list[Curve] = []
    fills: list[Fill] = []

    def tr(p) -> Point:
        q = pymupdf.Point(p) * matrix
        return (q.x, q.y)

    def add_polygon(points: list[Point], width: float, gray: bool) -> None:
        for a, b in zip(points, points[1:] + points[:1]):
            segments.append(Segment(a[0], a[1], b[0], b[1], width, gray))

    for path_id, path in enumerate(page.get_drawings()):
        width = path.get("width") or 0.0
        color = path.get("color")
        gray = bool(color) and 0.1 < color[0] < 0.9
        if path["type"] == "f":
            # Fills are only useful as shapes: keep the box, not the outline, so
            # the outline cannot be mistaken for a wall.
            corners = [tr(c) for c in (path["rect"].tl, path["rect"].tr, path["rect"].br, path["rect"].bl)]
            xs, ys = zip(*corners)
            fills.append(Fill(min(xs), min(ys), max(xs), max(ys)))
            continue
        for item in path["items"]:
            kind = item[0]
            if kind == "l":
                a, b = tr(item[1]), tr(item[2])
                segments.append(Segment(a[0], a[1], b[0], b[1], width, gray))
            elif kind == "c":
                curves.append(
                    Curve(tr(item[1]), tr(item[2]), tr(item[3]), tr(item[4]), width, path_id, gray)
                )
            elif kind == "re":
                r = item[1]
                add_polygon(
                    [tr((r.x0, r.y0)), tr((r.x1, r.y0)), tr((r.x1, r.y1)), tr((r.x0, r.y1))],
                    width,
                    gray,
                )
            elif kind == "qu":
                q = item[1]
                add_polygon([tr(q.ul), tr(q.ur), tr(q.lr), tr(q.ll)], width, gray)

    return Primitives(page.number, page.rect.width, page.rect.height, segments, curves, fills)


def extract_pdf_page(pdf_path: str | Path, page_index: int) -> Primitives:
    with pymupdf.open(pdf_path) as doc:
        return extract_page(doc[page_index])
