"""Read room labels and attach them to floor positions.

The drawing has no text layer, so text is read by OCR. OCR runs on an image drawn only
from the text line weight, so walls behind the letters cannot garble them. OCR output is
evidence for naming a room and never feeds a measurement.

A label reaches its room in one of two ways:
  - a leader line runs from the text to a dot inside the room,
  - or the text sits directly inside the room.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw

from keel.doors import dist
from keel.extract import Curve, Point, Segment, bezier_to_points
from keel.rooms import LeaderDot

TEXT_WIDTHS = (0.18,)
Region = tuple[float, float, float, float]



@dataclass(frozen=True)
class TextItem:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    confidence: float

    @property
    def center(self) -> Point:
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)


@dataclass(frozen=True)
class LabelBlock:
    """A room name with its compartment number, if one is printed."""

    name: str
    compartment: str | None
    center: Point
    x0: float
    y0: float
    x1: float
    y1: float
    confidence: float


@dataclass(frozen=True)
class PlacedLabel:
    block: LabelBlock
    anchor: Point  # floor position that identifies the room
    via: str  # "leader" or "in_room"


def parse_compartment(text: str) -> str | None:
    """Normalise a compartment number, or None if the text is not one.

    The format is deck-frame-side, as in 01-36-2. Digit-only OCR strings are split from
    the right: the last digit is the side, the two before it the frame, the rest the deck.
    """
    cleaned = text.strip().replace("—", "-").replace("_", "-").replace(" ", "")
    if not re.fullmatch(r"[-()\d]+", cleaned):
        return None
    if "(" in cleaned:
        return None  # negative-frame forms like 01-(-4)-0 are too unreliable to normalise
    digits = cleaned.replace("-", "")
    if not 3 <= len(digits) <= 6:
        return None
    side = digits[-1]
    frame = digits[-3:-1]
    deck = digits[:-3] or "0"
    return f"{deck}-{frame}-{side}"


def render_text_layer(
    segments: list[Segment],
    curves: list[Curve],
    region: Region,
    scale: float = 6.0,
    text_widths: tuple[float, ...] = TEXT_WIDTHS,
    exclude: set[Segment] | None = None,
) -> Image.Image:
    """Draw only the strokes with text line weights, black on white.

    exclude holds leader tails, which OCR would otherwise read as dashes joining two labels.
    """
    x0, y0, x1, y1 = region
    image = Image.new("L", (int((x1 - x0) * scale), int((y1 - y0) * scale)), 255)
    draw = ImageDraw.Draw(image)

    def is_text(width: float) -> bool:
        return any(abs(width - w) < 0.005 for w in text_widths)

    for s in segments:
        # Longer lines of this weight are leaders, not letter strokes.
        if is_text(s.width) and s.length < 8.0 and not (exclude and s in exclude):
            draw.line(
                [(s.x0 - x0) * scale, (s.y0 - y0) * scale, (s.x1 - x0) * scale, (s.y1 - y0) * scale],
                fill=0,
                width=2,
            )
    for c in curves:
        if is_text(c.width):
            pts = [((x - x0) * scale, (y - y0) * scale) for x, y in bezier_to_points(c, 5)]
            draw.line(pts, fill=0, width=2)
    return image


@lru_cache(maxsize=1)
def _ocr_engine():
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR()


def run_ocr(image: Image.Image, region: Region, scale: float) -> list[TextItem]:
    """OCR an image and return items in page points."""
    pixels = np.array(image.convert("RGB"))
    results, _ = _ocr_engine()(pixels)
    items = []
    for box, text, confidence in results or []:
        xs = [p[0] / scale + region[0] for p in box]
        ys = [p[1] / scale + region[1] for p in box]
        items.append(TextItem(text.strip(), min(xs), min(ys), max(xs), max(ys), float(confidence)))
    return items


def run_ocr_tiled(
    image: Image.Image, region: Region, scale: float, tile_px: int = 1800, overlap_px: int = 220
) -> list[TextItem]:
    """OCR large images piece by piece. The engine shrinks big images, which destroys small print."""
    width, height = image.size
    step = tile_px - overlap_px
    found: list[TextItem] = []
    for top in range(0, max(1, height - overlap_px), step):
        for left in range(0, max(1, width - overlap_px), step):
            crop = image.crop((left, top, min(width, left + tile_px), min(height, top + tile_px)))
            if crop.getextrema()[0] == 255:
                continue  # Blank tile: nothing to read.
            shifted = (region[0] + left / scale, region[1] + top / scale, 0.0, 0.0)
            found.extend(run_ocr(crop, shifted, scale))
    return _drop_overlaps(found)


def read_rotated_blocks(image: Image.Image, region: Region, scale: float, min_confidence: float = 0.85) -> list[LabelBlock]:
    """Labels printed vertically. Turn the page so they read upright, then map back to the page."""
    width, height = image.size
    turned = image.rotate(-90, expand=True)  # (x, y) on the page -> (height - y, x)
    items = run_ocr_tiled(turned, (0.0, 0.0, 0.0, 0.0), scale)
    blocks = []
    for block in group_blocks(items):
        words = re.sub(r"[^A-Z]", "", block.name.upper())
        if len(words) < 4 or block.confidence < min_confidence:
            continue  # Sideways horizontal text reads as short noise.
        top = region[1] + (height / scale - block.x1)
        bottom = region[1] + (height / scale - block.x0)
        left = region[0] + block.y0
        right = region[0] + block.y1
        blocks.append(
            LabelBlock(block.name, block.compartment, ((left + right) / 2, (top + bottom) / 2), left, top, right, bottom, block.confidence)
        )
    return blocks


def _drop_overlaps(items: list[TextItem]) -> list[TextItem]:
    """Text in the overlap between tiles is read twice. Keep the longer, more confident copy."""
    kept: list[TextItem] = []
    for item in sorted(items, key=lambda i: (-len(i.text), -i.confidence)):
        area = max((item.x1 - item.x0) * (item.y1 - item.y0), 1e-6)
        duplicate = False
        for other in kept:
            overlap_w = min(item.x1, other.x1) - max(item.x0, other.x0)
            overlap_h = min(item.y1, other.y1) - max(item.y0, other.y0)
            if overlap_w > 0 and overlap_h > 0 and overlap_w * overlap_h / area > 0.5:
                duplicate = True
                break
        if not duplicate:
            kept.append(item)
    return kept


def group_blocks(
    items: list[TextItem], max_gap: float = 2.5, max_center_offset: float = 25.0
) -> list[LabelBlock]:
    """Stack text lines into blocks: name lines above, compartment number at the bottom."""
    ordered = sorted(items, key=lambda i: (i.center[1], i.center[0]))
    used: set[int] = set()
    blocks: list[LabelBlock] = []
    for index, first in enumerate(ordered):
        if index in used:
            continue
        used.add(index)
        members = [first]
        current = first
        while True:
            next_index = None
            for j, candidate in enumerate(ordered):
                if j in used:
                    continue
                gap = candidate.y0 - current.y1
                if -3.0 <= gap <= max_gap and abs(candidate.center[0] - current.center[0]) <= max_center_offset:
                    next_index = j
                    break
            if next_index is None:
                break
            current = ordered[next_index]
            used.add(next_index)
            members.append(current)
            if parse_compartment(current.text):
                break  # the number closes a block

        names = [m.text for m in members if not parse_compartment(m.text)]
        numbers = [parse_compartment(m.text) for m in members if parse_compartment(m.text)]
        if not names and not numbers:
            continue
        x0 = min(m.x0 for m in members)
        y0 = min(m.y0 for m in members)
        x1 = max(m.x1 for m in members)
        y1 = max(m.y1 for m in members)
        blocks.append(
            LabelBlock(
                " ".join(names).strip("-— ").strip(),
                numbers[0] if numbers else None,
                ((x0 + x1) / 2, (y0 + y1) / 2),
                x0,
                y0,
                x1,
                y1,
                min(m.confidence for m in members),
            )
        )
    return blocks


class SegmentIndex:
    """Quickly narrows the lines worth looking at. Every result stays in input order, and the
    exact checks still run on what it returns, so it only saves time. Its limits are slightly
    loose so rounding can never drop a line the exact check would keep.
    """

    SLACK = 1e-6

    def __init__(self, segments: list[Segment]):
        self.segments = segments
        data = np.array([(s.x0, s.y0, s.x1, s.y1, s.width) for s in segments], dtype=float).reshape(-1, 5)
        self.x0, self.y0, self.x1, self.y1, self.width = data.T
        self.length = np.hypot(self.x1 - self.x0, self.y1 - self.y0)

    def _pick(self, mask: np.ndarray) -> list[Segment]:
        return [self.segments[int(i)] for i in np.flatnonzero(mask)]

    def _near(self, point: Point, radius: float) -> np.ndarray:
        limit = radius + self.SLACK
        return (np.hypot(self.x0 - point[0], self.y0 - point[1]) <= limit) | (
            np.hypot(self.x1 - point[0], self.y1 - point[1]) <= limit
        )

    def _same_weight(self, width: float) -> np.ndarray:
        return np.abs(self.width - width) <= 0.005 + self.SLACK

    def touching(self, point: Point, radius: float) -> list[Segment]:
        return self._pick(self._near(point, radius))

    def same_weight_longer_than(self, width: float, length: float) -> list[Segment]:
        return self._pick(self._same_weight(width) & (self.length > length - self.SLACK))

    def along_line(self, width: float, origin: Point, ux: float, uy: float, tol: float) -> list[Segment]:
        limit = tol + self.SLACK
        offset0 = np.abs((self.x0 - origin[0]) * uy - (self.y0 - origin[1]) * ux)
        offset1 = np.abs((self.x1 - origin[0]) * uy - (self.y1 - origin[1]) * ux)
        return self._pick(self._same_weight(width) & (offset0 <= limit) & (offset1 <= limit))

    def elbows_at(self, width: float, tip: Point, radius: float) -> list[Segment]:
        return self._pick(self._same_weight(width) & self._near(tip, radius))


def _refine_through_dot(
    near: Point, ux: float, uy: float, first: Segment, dot: LeaderDot, index: SegmentIndex
) -> tuple[Point, float, float]:
    """The piece at a dot is often under 2 pt, too short to give an accurate direction.

    A leader's line passes through the dot's centre, so use the longest same-weight piece
    that does, on the same side and in roughly the same direction.
    """
    best, best_length = None, 3.0
    for s in index.same_weight_longer_than(first.width, best_length):
        if abs(s.width - first.width) > 0.005 or s.length <= best_length:
            continue
        a, b = (s.x0, s.y0), (s.x1, s.y1)
        near_end, far_end = (a, b) if dist(a, dot.point) <= dist(b, dot.point) else (b, a)
        vx, vy = (far_end[0] - near_end[0]) / s.length, (far_end[1] - near_end[1]) / s.length
        if vx * ux + vy * uy < 0.97:
            continue
        off = abs((dot.x - near_end[0]) * vy - (dot.y - near_end[1]) * vx)
        ahead = (near_end[0] - dot.x) * ux + (near_end[1] - dot.y) * uy
        if off <= 0.5 and ahead > -1.0:
            best, best_length = (vx, vy), s.length
    if best is None:
        return near, ux, uy
    return dot.point, best[0], best[1]


def _follow_leader(
    first: Segment,
    dot: LeaderDot,
    index: SegmentIndex,
    line_tol: float,
    max_gap: float,
    strokes: set[Segment] | None = None,
) -> list[Point]:
    """Possible far ends of one leader, furthest first.

    From the line at the dot, walk along collinear pieces of the same weight, then take the
    short elbow to the text if there is one. Leaders are broken where they cross walls.
    """
    if dist((first.x0, first.y0), dot.point) <= dist((first.x1, first.y1), dot.point):
        near, far = (first.x0, first.y0), (first.x1, first.y1)
    else:
        near, far = (first.x1, first.y1), (first.x0, first.y0)
    span = dist(near, far)
    if span == 0:
        return []
    ux, uy = (far[0] - near[0]) / span, (far[1] - near[1]) / span
    if span < 4.0:
        near, ux, uy = _refine_through_dot(near, ux, uy, first, dot, index)
        span = dist(near, far) if near != dot.point else 0.0

    pieces = []
    for s in index.along_line(first.width, near, ux, uy, line_tol):
        if s.length < 0.2 or abs(s.width - first.width) > 0.005:
            continue
        offsets = []
        for p in ((s.x0, s.y0), (s.x1, s.y1)):
            dx, dy = p[0] - near[0], p[1] - near[1]
            if abs(dx * uy - dy * ux) > line_tol:
                break
            offsets.append(dx * ux + dy * uy)
        else:
            if max(offsets) > span:
                pieces.append((min(offsets), max(offsets)))

    stops = [span]
    reach = span
    for low, high in sorted(pieces):
        if low > reach + max_gap:
            break
        if high > reach:
            reach = high
            stops.append(reach)

    ends: list[Point] = []
    for stop in reversed(stops):
        tip = (near[0] + ux * stop, near[1] + uy * stop)
        for s in index.elbows_at(first.width, tip, 0.6):
            a, b = (s.x0, s.y0), (s.x1, s.y1)
            if 1.0 <= s.length <= 14.0 and abs(s.width - first.width) <= 0.005:
                # Only a real turn counts as an elbow, not the next piece of the same line.
                turn = abs((s.x1 - s.x0) * uy - (s.y1 - s.y0) * ux) / s.length
                if turn > 0.25:
                    if dist(a, tip) <= 0.6:
                        ends.append(b)
                    elif dist(b, tip) <= 0.6:
                        ends.append(a)
                    else:
                        continue
                    if strokes is not None:
                        strokes.add(s)
        ends.append(tip)
    return ends


def trace_leader_tails(
    dot: LeaderDot,
    segments: list[Segment],
    margin: float = 0.3,
    line_tol: float = 0.5,
    max_gap: float = 30.0,
    strokes: set[Segment] | None = None,
    index: SegmentIndex | None = None,
) -> list[list[Point]]:
    """One list of possible far ends for each line that really starts at this dot."""
    index = index or SegmentIndex(segments)
    tol = dot.radius + margin
    tails = []
    for s in index.touching(dot.point, tol):
        if s.length < 0.7:
            continue
        a, b = (s.x0, s.y0), (s.x1, s.y1)
        near = min(dist(a, dot.point), dist(b, dot.point))
        far = max(dist(a, dot.point), dist(b, dot.point))
        # The line must run away from the dot, not pass by it.
        if near <= tol and far > near + 0.5:
            tails.append(_follow_leader(s, dot, index, line_tol, max_gap, strokes))
    return tails


def trace_all_leaders(dots: list[LeaderDot], segments: list[Segment]) -> tuple[list[list[list[Point]]], set[Segment]]:
    """Every dot's possible far ends, and the short elbows joining leaders to their text."""
    index = SegmentIndex(segments)
    strokes: set[Segment] = set()
    traces = [trace_leader_tails(dot, segments, strokes=strokes, index=index) for dot in dots]
    return traces, strokes


def leader_tail_strokes(dots: list[LeaderDot], segments: list[Segment]) -> set[Segment]:
    """The short elbows joining leaders to their text."""
    return trace_all_leaders(dots, segments)[1]


def block_has_leader(
    block: LabelBlock,
    segments: list[Segment],
    tails: set[Segment] | None = None,
    touch: float = 2.5,
    min_length: float = 6.0,
    max_width: float = 0.2,
) -> bool:
    """A thin line ending at the text's edge means the text names some other place.

    Letter strokes are shorter than min_length and walls are thicker than max_width, so
    neither counts. Traced leader tails always count, whatever their weight.
    """
    for s in segments:
        known_tail = bool(tails) and s in tails
        if not known_tail and (s.length < min_length or s.width > max_width):
            continue
        for p in ((s.x0, s.y0), (s.x1, s.y1)):
            inside = block.x0 <= p[0] <= block.x1 and block.y0 <= p[1] <= block.y1
            if not inside and _gap_to_block(p, block) <= touch:
                other = (s.x1, s.y1) if p == (s.x0, s.y0) else (s.x0, s.y0)
                if _gap_to_block(other, block) > touch:
                    return True
    return False


def _gap_to_block(point: Point, block: LabelBlock) -> float:
    nx = max(block.x0, min(point[0], block.x1))
    ny = max(block.y0, min(point[1], block.y1))
    return dist((nx, ny), point)


def place_labels(
    blocks: list[LabelBlock],
    dots: list[LeaderDot],
    segments: list[Segment],
    max_tail_distance: float = 10.0,
    traces: list[list[list[Point]]] | None = None,
) -> list[PlacedLabel]:
    """Pair dots with text blocks, closest first. Unclaimed blocks count as in-room labels.

    Each leader offers its far ends, furthest first. A leader ends at its text, so the first
    end that reaches a block decides, and text it merely passes on the way is ignored.
    """
    if traces is None:
        traces = trace_all_leaders(dots, segments)[0]
    candidates = []
    for dot_index, dot in enumerate(dots):
        for ends in traces[dot_index]:
            for rank, end in enumerate(ends):
                gaps = [(_gap_to_block(end, block), block_index) for block_index, block in enumerate(blocks)]
                near = [g for g in gaps if g[0] < max_tail_distance]
                if near:
                    gap, block_index = min(near)
                    candidates.append((rank, gap, dot_index, block_index))
                    break

    placed: list[PlacedLabel] = []
    used_dots: set[int] = set()
    claimed: set[int] = set()
    for _, _, dot_index, block_index in sorted(candidates, key=lambda c: (c[1], c[0])):
        if dot_index in used_dots or block_index in claimed:
            continue
        used_dots.add(dot_index)
        claimed.add(block_index)
        placed.append(PlacedLabel(blocks[block_index], dots[dot_index].point, "leader"))
    for index, block in enumerate(blocks):
        if index not in claimed:
            placed.append(PlacedLabel(block, block.center, "in_room"))
    return placed
