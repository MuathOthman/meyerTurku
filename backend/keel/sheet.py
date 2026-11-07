"""Reading a whole drawing sheet: which deck plans it holds, and what scale it was drawn at.

A general arrangement sheet often shows every deck, and prints its scale and frame spacing as
text. Nothing here is guessed: a scale is only returned when two independent readings agree.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pymupdf

from keel.calibrate import CalibrationError, detect_frame_ruler
from keel.extract import Segment

Region = tuple[float, float, float, float]
PT_MM = 25.4 / 72
DECK_LABEL = re.compile(r"\b(DECK|TRUNK|WHEELHOUSE)\b", re.IGNORECASE)
MAX_SCALE_DISAGREEMENT = 0.02


@dataclass(frozen=True)
class DeckPlan:
    name: str
    region: Region


@dataclass(frozen=True)
class SheetScale:
    mm_per_pt: float
    relative_error: float
    note: str


def _blocks(ink: np.ndarray, x0: int, y0: int, x1: int, y1: int, gap: int, out: list) -> None:
    """Split the ink into blocks at the blank rows and columns between them."""
    part = ink[y0:y1, x0:x1]
    rows, cols = np.flatnonzero(part.any(axis=1)), np.flatnonzero(part.any(axis=0))
    if not len(rows) or not len(cols):
        return
    y0, y1 = y0 + int(rows[0]), y0 + int(rows[-1]) + 1
    x0, x1 = x0 + int(cols[0]), x0 + int(cols[-1]) + 1
    part = ink[y0:y1, x0:x1]
    for axis, length in ((1, y1 - y0), (0, x1 - x0)):
        filled = part.any(axis=axis)
        start = None
        for i in range(length):
            if not filled[i] and start is None:
                start = i
            elif filled[i] and start is not None:
                if i - start >= gap:
                    if axis == 1:
                        _blocks(ink, x0, y0, x1, y0 + start, gap, out)
                        _blocks(ink, x0, y0 + i, x1, y1, gap, out)
                    else:
                        _blocks(ink, x0, y0, x0 + start, y1, gap, out)
                        _blocks(ink, x0 + i, y0, x1, y1, gap, out)
                    return
                start = None
    out.append((x0, y0, x1, y1))


def find_deck_plans(path: str | Path, page: int = 0) -> list[DeckPlan]:
    """The deck plans on a sheet, found from their printed names. Empty if there are none."""
    dpi = 36
    with pymupdf.open(path) as document:
        sheet = document[page]
        labels = [
            (" ".join(b[4].split()), b[0], b[1], b[2], b[3])
            for b in sheet.get_text("blocks")
            if b[6] == 0 and len(b[4].strip()) < 40 and DECK_LABEL.search(b[4])
        ]
        if not labels:
            return []
        pixmap = sheet.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        scale = 72 / dpi
        gray = np.frombuffer(pixmap.samples, np.uint8).reshape(pixmap.h, pixmap.w)
        # A sheet border would join everything, so read inside it.
        margin = int(0.012 * max(pixmap.w, pixmap.h))
        ink = (gray < 215).astype(np.uint8)
        ink[:margin], ink[-margin:], ink[:, :margin], ink[:, -margin:] = 0, 0, 0, 0
        ink[:, int(pixmap.w * 0.74):] = 0  # Title block and side views sit in the right-hand column.
        for name, x0, y0, x1, y1 in labels:  # Names would join a plan to its neighbour.
            ink[int(y0 / scale) - 1 : int(y1 / scale) + 2, int(x0 / scale) - 1 : int(x1 / scale) + 2] = 0
        blocks: list[tuple[int, int, int, int]] = []
        _blocks(ink, 0, 0, pixmap.w, pixmap.h, 4, blocks)
    big = [b for b in blocks if (b[2] - b[0]) * (b[3] - b[1]) * scale * scale > 40000]
    if not big:
        return []
    owners: dict[tuple, list] = {}
    for label in labels:
        cx, cy = (label[1] + label[3]) / 2 / scale, (label[2] + label[4]) / 2 / scale
        best = min(big, key=lambda b: max(b[0] - cx, 0, cx - b[2]) + max(b[1] - cy, 0, cy - b[3]))
        if max(best[0] - cx, 0, cx - best[2]) + max(best[1] - cy, 0, cy - best[3]) <= 150 / scale:
            owners.setdefault(best, []).append(label)
    plans = []
    pad = 6
    for block, owned in owners.items():
        for name, (x0, y0, x1, y1) in _split_shared_block(ink, block, owned, scale):
            plans.append(DeckPlan(name, (x0 * scale - pad, y0 * scale - pad, x1 * scale + pad, y1 * scale + pad)))
    return sorted(plans, key=lambda p: (p.region[1], p.region[0]))


def _split_shared_block(ink: np.ndarray, block: tuple, labels: list, scale: float) -> list[tuple[str, tuple]]:
    """Plans touching each other, by a crane arc say, share a block. Their names separate them.

    Names sit at the foot of each plan, so rows end just below a name. Within a row, plans side
    by side are cut at the emptiest columns.
    """
    x0, y0, x1, y1 = block
    if len(labels) == 1:
        return [(labels[0][0], block)]
    rows: list[list] = []
    for label in sorted(labels, key=lambda item: item[4]):
        if rows and label[4] / scale - rows[-1][-1][4] / scale < 60 / scale:
            rows[-1].append(label)
        else:
            rows.append([label])
    result = []
    top = y0
    for index, row in enumerate(rows):
        foot = max(item[4] for item in row) / scale
        if index == len(rows) - 1:
            bottom = y1
        else:
            search = ink[int(foot) : int(foot) + 30, x0:x1].sum(axis=1)
            bottom = int(foot) + int(np.argmin(search)) if len(search) else int(foot)
        band = ink[top:bottom, x0:x1]
        columns = band.sum(axis=0)
        cuts = [x0, x1]
        if len(row) > 1:
            low = columns <= 0.03 * max(1, bottom - top)
            runs, start = [], None
            # Only gaps between plans count, not the blank margin outside them.
            for i, value in enumerate(low):
                if value and start is None:
                    start = i
                elif not value and start is not None:
                    if start > 0:
                        runs.append((i - start, start, i))
                    start = None
            widest = sorted(runs, reverse=True)[: len(row) - 1]
            cuts = sorted([x0, x1] + [x0 + (a + b) // 2 for _, a, b in widest])
        spans = list(zip(cuts, cuts[1:]))
        for label in row:
            cx = (label[1] + label[3]) / 2 / scale
            left, right = min(spans, key=lambda s: 0 if s[0] <= cx <= s[1] else min(abs(cx - s[0]), abs(cx - s[1])))
            part = ink[top:bottom, left:right]
            r, c = np.flatnonzero(part.sum(axis=1) > 1), np.flatnonzero(part.sum(axis=0) > 1)
            if len(r) and len(c):
                result.append((label[0], (left + int(c[0]), top + int(r[0]), left + int(c[-1]) + 1, top + int(r[-1]) + 1)))
        top = bottom
    return result


def read_sheet_scale(path: str | Path, page: int, segments: list[Segment]) -> SheetScale | None:
    """Printed scale checked against the frame ruler. None unless both exist and they agree."""
    with pymupdf.open(path) as document:
        text = document[page].get_text()
    printed = re.search(r"(?<![\d.:])1\s*:\s*(\d{1,4})(?![\d:])", text)
    frame = re.search(r"FRAME\s+SPACING", text, re.IGNORECASE)
    if not printed or not frame:
        return None
    spacing_candidates = [int(v) for v in re.findall(r"(?m)^\s*(\d{3,4})\s*$", text) if 300 <= int(v) <= 1200]
    if not spacing_candidates:
        return None
    try:
        ruler = detect_frame_ruler(segments, min_ticks=12)
    except CalibrationError:
        return None
    from_print = int(printed.group(1)) * PT_MM
    for spacing_mm in spacing_candidates:
        from_ruler = spacing_mm / ruler.spacing_pt
        error = abs(from_ruler - from_print) / from_print
        if error <= MAX_SCALE_DISAGREEMENT:
            return SheetScale(
                from_ruler,
                max(error, 0.002),
                f"Scale read from the sheet: frame spacing {spacing_mm} mm on the frame ruler gives "
                f"{from_ruler:.2f} mm/pt, within {error:.1%} of the printed 1:{printed.group(1)}.",
            )
    return None


def sheet_scale(path: str | Path, page: int, segments: list[Segment], plans: list[DeckPlan]) -> SheetScale | None:
    """The sheet has one printed scale. Use the plan whose frame ruler agrees with it best."""
    best = None
    for plan in plans:
        x0, y0, x1, y1 = plan.region
        inside = [s for s in segments if x0 <= s.midpoint[0] <= x1 and y0 <= s.midpoint[1] <= y1]
        scale = read_sheet_scale(path, page, inside)
        if scale is not None and (best is None or scale.relative_error < best.relative_error):
            best = scale
    return best if plans else read_sheet_scale(path, page, segments)
