"""Split any plan image into separate spaces, using image geometry only.

This route needs no vector data, no line-weight knowledge and no labels, so it can take a
scan or a photo-quality export. It finds spaces, and measures only if given a scale.

  1. Separate ink from floor, removing text and hairlines.
  2. Each connected piece of floor is a candidate space.
  3. A door gap can join two rooms, so split pieces at narrow necks using a watershed on
     the distance from the walls.
  4. Merge pieces whose shared opening is about as wide as they are: that is one room.

No AI is involved in this step.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pymupdf


@dataclass
class RasterSpace:
    number: int
    area_px: int
    bbox: tuple[int, int, int, int]  # x0, y0, x1, y1
    center: tuple[int, int]  # most open point, where a label tag fits best
    inscribed_px: float  # diameter of the largest circle that fits
    contour: np.ndarray


@dataclass
class Segmentation:
    labels: np.ndarray  # 0 is not a space, otherwise the space number
    spaces: list[RasterSpace]
    neck_px: float


def load_gray(path: str | Path, page: int = 0, dpi: int = 400, region=None) -> tuple[np.ndarray, float]:
    """Read a PDF page or an image as grayscale. Returns (image, points per pixel).

    region is in PDF points for PDFs and pixels for images. Points per pixel is 0 for images,
    because an image has no intrinsic physical size.
    """
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        with pymupdf.open(path) as document:
            clip = pymupdf.Rect(*region) if region else None
            pixmap = document[page].get_pixmap(dpi=dpi, clip=clip, colorspace=pymupdf.csGRAY)
            image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.h, pixmap.w).copy()
        return image, 72.0 / dpi
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError(f"cannot read image: {path}")
    if region:
        x0, y0, x1, y1 = (int(v) for v in region)
        image = image[y0:y1, x0:x1]
    return image, 0.0


def _stroke_width(ink: np.ndarray) -> float:
    """Typical line thickness: twice the median distance-to-edge along stroke centres."""
    distance = cv2.distanceTransform(ink, cv2.DIST_L2, 3)
    ridge = cv2.dilate(distance, np.ones((3, 3), np.uint8)) == distance
    values = distance[ridge & (ink > 0)]
    return 2.0 * float(np.median(values)) if values.size else 1.0


def extract_walls(gray: np.ndarray, min_component_ratio: float = 0.00012) -> np.ndarray:
    """Binary image of walls: ink minus hairlines and small marks such as letters."""
    # Otsu copes with scans and exports alike, but gray hatching must not count as wall.
    threshold, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, ink = cv2.threshold(gray, min(threshold, 150), 255, cv2.THRESH_BINARY_INV)
    # Hairlines (leaders, dimension lines, thin text) vanish under a small opening.
    size = max(2, int(round(_stroke_width(ink) * 0.75)))
    thick = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (size, 1)))
    thick |= cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, size)))
    # Letters are small separate marks. Walls connect into large structures.
    count, labels, stats, _ = cv2.connectedComponentsWithStats(thick, connectivity=8)
    span = min_component_ratio * max(gray.shape) ** 2
    keep = np.zeros(count, dtype=bool)
    for index in range(1, count):
        w, h = stats[index, cv2.CC_STAT_WIDTH], stats[index, cv2.CC_STAT_HEIGHT]
        keep[index] = w * h >= span
    return (keep[labels] * 255).astype(np.uint8)


def _split_at_necks(free: np.ndarray, neck_px: float) -> np.ndarray:
    """Watershed from the parts of the floor wider than a door gap."""
    distance = cv2.distanceTransform(free, cv2.DIST_L2, 5)
    _, markers = cv2.connectedComponents((distance > neck_px / 2).astype(np.uint8))
    # Unreached floor belongs to the nearest marker; walls are a separate basin.
    markers = markers + 1
    markers[(free > 0) & (distance <= neck_px / 2)] = 0
    relief = cv2.cvtColor(free, cv2.COLOR_GRAY2BGR)
    relief[..., 0] = np.clip(255 - distance * 8, 0, 255).astype(np.uint8)
    relief[..., 1] = relief[..., 0]
    relief[..., 2] = relief[..., 0]
    result = cv2.watershed(relief, markers.astype(np.int32))
    result = result - 1
    result[(result < 1) | (free == 0)] = 0
    return result


def _merge_wide_openings(labels: np.ndarray, free: np.ndarray, ratio: float) -> np.ndarray:
    """Merge neighbours whose shared opening is nearly as wide as the narrower of them."""
    distance = cv2.distanceTransform(free, cv2.DIST_L2, 5)
    while True:
        count = labels.max() + 1
        widths = np.zeros(count)
        np.maximum.at(widths, labels.ravel(), distance.ravel())
        widths *= 2
        shared: dict[tuple[int, int], float] = {}
        for shift_y, shift_x in ((0, 2), (2, 0)):
            a = labels[: labels.shape[0] - shift_y, : labels.shape[1] - shift_x]
            b = labels[shift_y:, shift_x:]
            d = distance[: labels.shape[0] - shift_y, : labels.shape[1] - shift_x]
            mask = (a != b) & (a > 0) & (b > 0)
            for p, q, value in zip(a[mask], b[mask], d[mask]):
                key = (min(p, q), max(p, q))
                shared[key] = max(shared.get(key, 0.0), float(value) * 2)
        merged = False
        for (p, q), opening in sorted(shared.items(), key=lambda kv: -kv[1]):
            if opening >= ratio * min(widths[p], widths[q]):
                labels[labels == q] = p
                merged = True
                break
        if not merged:
            return labels


def segment(
    gray: np.ndarray,
    neck_px: float,
    min_area_ratio: float = 0.0004,
    merge_ratio: float = 0.8,
) -> Segmentation:
    """Number the separate spaces in a plan image."""
    walls = extract_walls(gray)
    free = cv2.bitwise_not(walls)
    labels = _split_at_necks(free, neck_px)
    labels = _merge_wide_openings(labels, free, merge_ratio)

    minimum = min_area_ratio * neck_px ** 2 * 2500
    spaces: list[RasterSpace] = []
    output = np.zeros(labels.shape, dtype=np.int32)
    h, w = labels.shape
    for value in np.unique(labels):
        if value == 0:
            continue
        mask = (labels == value).astype(np.uint8)
        area = int(mask.sum())
        if area < minimum:
            continue
        x, y, bw, bh = cv2.boundingRect(mask)
        # Whatever touches the crop border is the page outside, not a room.
        # The watershed leaves a one-pixel rim, so allow a small margin.
        if x <= 2 or y <= 2 or x + bw >= w - 2 or y + bh >= h - 2:
            if area > 0.25 * h * w or (bw >= 0.9 * w or bh >= 0.9 * h):
                continue
        distance = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
        _, peak, _, location = cv2.minMaxLoc(distance)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        number = len(spaces) + 1
        output[labels == value] = number
        spaces.append(
            RasterSpace(number, area, (x, y, x + bw, y + bh), location, peak * 2, max(contours, key=cv2.contourArea))
        )
    return Segmentation(output, spaces, neck_px)


def content_box(gray: np.ndarray) -> tuple[int, int, int, int]:
    """The drawn plan, ignoring the sheet frame and anything spanning most of the page."""
    _, ink = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    height, width = gray.shape
    best = None
    for index in range(1, count):
        x, y, w, h, area = stats[index]
        if w >= 0.8 * width or h >= 0.8 * height:
            continue  # The sheet frame.
        if best is None or w * h > best[2] * best[3]:
            best = (x, y, w, h)
    if best is None:
        return 0, 0, width, height
    x, y, w, h = best
    return x, y, x + w, y + h


def choose_neck(gray: np.ndarray, candidates=None) -> float:
    """Pick the door-gap size without a scale: the widest setting in the most stable run.

    Space counts barely change while the setting lies between typical door widths and room
    widths. This is a heuristic, so the result is reported for the engineer to confirm.
    """
    x0, y0, x1, y1 = content_box(gray)
    long_side = max(x1 - x0, y1 - y0)
    candidates = candidates or [long_side * f for f in (0.006, 0.008, 0.01, 0.0125, 0.015, 0.018, 0.022, 0.027)]
    walls = extract_walls(gray)
    free = cv2.bitwise_not(walls)
    distance = cv2.distanceTransform(free, cv2.DIST_L2, 5)
    counts = [cv2.connectedComponents((distance > c / 2).astype(np.uint8))[0] for c in candidates]
    best_index, best_change = 1, float("inf")
    for i in range(1, len(counts)):
        change = abs(counts[i] - counts[i - 1]) / max(counts[i - 1], 1)
        if change <= best_change:
            best_index, best_change = i, change
    return candidates[best_index]


def draw_numbers(gray: np.ndarray, seg: Segmentation, tint: float = 0.3, only: set[int] | None = None) -> np.ndarray:
    """A color image with each space tinted and numbered, for people and for the vision model."""
    image = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    rng = np.random.default_rng(7)
    overlay = image.copy()
    size = int(seg.labels.max()) + 1 if seg.labels.size else 1
    palette = np.zeros((size, 3), dtype=np.uint8)
    tinted = np.zeros(size, dtype=bool)
    for space in seg.spaces:
        color = rng.integers(90, 240, 3)
        if space.number < size:
            palette[space.number], tinted[space.number] = color, True
    mask = tinted[seg.labels]
    overlay[mask] = palette[seg.labels[mask]]
    image = cv2.addWeighted(overlay, tint, image, 1 - tint, 0)
    scale = max(0.5, max(gray.shape) / 5000)
    for space in seg.spaces:
        if only is not None and space.number not in only:
            continue
        text = str(space.number)
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
        x, y = space.center
        cv2.rectangle(image, (x - tw // 2 - 4, y - th // 2 - 4), (x + tw // 2 + 4, y + th // 2 + 4), (0, 0, 180), -1)
        cv2.putText(image, text, (x - tw // 2, y + th // 2), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 2, cv2.LINE_AA)
    return image
