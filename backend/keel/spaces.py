"""Find every separate space in a new drawing, with no labels or per-drawing setup."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pymupdf
from shapely.geometry import Polygon

from keel.doors import DetectedDoor, doors_from_arcs, find_door_arcs
from keel.extract import Primitives, Segment, extract_page
from keel.raster import RasterSpace, Segmentation, load_gray, segment
from keel.rooms import build_wall_lines, detect_leader_dots, find_leader_lines, free_cells

# A vector page has far more drawn items than a scanned page, which has almost none.
MIN_VECTOR_ITEMS = 1000
Region = tuple[float, float, float, float]


@dataclass
class FoundSpaces:
    route: str  # vector | raster
    segmentation: Segmentation
    gray: np.ndarray
    px_per_unit: float  # pixels per PDF point or per image pixel
    region: Region | None
    doors: list[DetectedDoor]
    cells_pt: dict[int, Polygon]  # vector route only, by space number
    primitives: Primitives | None = None
    dots: list | None = None


def detect_wall_widths(segments: list[Segment], min_width: float = 0.2, min_share: float = 0.01) -> tuple[float, ...]:
    """Line weights that draw walls: thick enough and used for long straight runs.

    Letters use short strokes and hairlines are too thin, so neither qualifies.
    """
    long_runs: dict[float, float] = defaultdict(float)
    for s in segments:
        if s.length >= 8.0 and not s.gray:
            long_runs[round(s.width, 2)] += s.length
    total = sum(long_runs.values()) or 1.0
    return tuple(sorted(w for w, length in long_runs.items() if w >= min_width and length / total >= min_share))


def is_vector_page(path: str | Path, page: int = 0) -> bool:
    if Path(path).suffix.lower() != ".pdf":
        return False
    with pymupdf.open(path) as document:
        return len(document[page].get_drawings()) >= MIN_VECTOR_ITEMS


def _in_region(point, region) -> bool:
    return region[0] <= point[0] <= region[2] and region[1] <= point[1] <= region[3]


def vector_spaces(
    path: str | Path,
    page: int,
    region: Region,
    mm_per_pt: float | None = None,
    dpi: int = 300,
    min_area_pt2: float = 40.0,
    min_inscribed_pt: float = 5.0,
) -> FoundSpaces:
    """Spaces from drawn walls. This is the precise route."""
    with pymupdf.open(path) as document:
        primitives: Primitives = extract_page(document[page])
    curves = [c for c in primitives.curves if _in_region(c.p0, region) and _in_region(c.p3, region)]
    segments = [s for s in primitives.segments if _in_region(s.midpoint, region) and s.length > 0.3]
    widths = detect_wall_widths(segments)
    walls = [s for s in segments if any(abs(s.width - w) < 0.005 for w in widths)]
    # Without a scale, door size is unknown, so allow a wide range. Wall evidence still filters.
    low, high = (400 / mm_per_pt, 1300 / mm_per_pt) if mm_per_pt else (4.0, 25.0)
    arcs = find_door_arcs(curves, low, high)
    doors, _ = doors_from_arcs(arcs, segments, walls)
    all_dots = detect_leader_dots(primitives.fills, None, segments=primitives.segments)
    dots = [d for d in all_dots if _in_region(d.point, region)]
    leaders = find_leader_lines(primitives.segments, dots)
    cells = free_cells(region, build_wall_lines(segments, curves, doors, leaders, arcs, wall_widths=widths))

    gray, pt_per_px = load_gray(path, page, dpi, region)
    scale = 1.0 / pt_per_px
    labels = np.zeros(gray.shape, dtype=np.int32)
    spaces: list[RasterSpace] = []
    by_number: dict[int, Polygon] = {}
    height, width = gray.shape
    for cell in sorted(cells, key=lambda c: (c.bounds[1], c.bounds[0])):
        if cell.area < min_area_pt2:
            continue
        minx, miny, maxx, maxy = cell.bounds
        touches_edge = minx <= region[0] + 1 or miny <= region[1] + 1 or maxx >= region[2] - 1 or maxy >= region[3] - 1
        if touches_edge and cell.area > 0.25 * (region[2] - region[0]) * (region[3] - region[1]):
            continue
        mask = np.zeros(gray.shape, dtype=np.uint8)
        ring = np.array([[(x - region[0]) * scale, (y - region[1]) * scale] for x, y in cell.exterior.coords], np.int32)
        cv2.fillPoly(mask, [ring], 1)
        for hole in cell.interiors:
            inner = np.array([[(x - region[0]) * scale, (y - region[1]) * scale] for x, y in hole.coords], np.int32)
            cv2.fillPoly(mask, [inner], 0)
        distance = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
        _, peak, _, location = cv2.minMaxLoc(distance)
        if peak * 2 / scale < min_inscribed_pt:
            continue  # slivers and furniture detail
        number = len(spaces) + 1
        labels[(mask > 0) & (labels == 0)] = number
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        x, y, bw, bh = cv2.boundingRect(mask)
        spaces.append(
            RasterSpace(number, int(mask.sum()), (x, y, x + bw, y + bh), location, peak * 2, max(contours, key=cv2.contourArea))
        )
        by_number[number] = cell
    assert labels.shape == (height, width)
    return FoundSpaces("vector", Segmentation(labels, spaces, 0.0), gray, scale, region, doors, by_number, primitives, dots)


def raster_spaces(path: str | Path, page: int = 0, region=None, neck_px: float | None = None) -> FoundSpaces:
    """Spaces from pixels only. Works on any image, with less precision than the vector route."""
    from keel.raster import choose_neck

    gray, pt_per_px = load_gray(path, page, 300, region)
    neck = neck_px or choose_neck(gray)
    scale = 1.0 / pt_per_px if pt_per_px else 1.0
    return FoundSpaces("raster", segment(gray, neck), gray, scale, region, [], {})


def find_spaces(path: str | Path, page: int = 0, region: Region | None = None, mm_per_pt: float | None = None) -> FoundSpaces:
    if is_vector_page(path, page):
        if region is None:
            with pymupdf.open(path) as document:
                rect = document[page].rect
            margin = 0.06
            region = (
                rect.width * margin, rect.height * margin,
                rect.width * (1 - margin), rect.height * (1 - margin),
            )
        return vector_spaces(path, page, region, mm_per_pt)
    return raster_spaces(path, page, region)
