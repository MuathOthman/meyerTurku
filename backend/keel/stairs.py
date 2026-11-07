"""Stairs on a plan: a run of parallel treads of equal length at a steady spacing.

Treads are real lines in the drawing, so the width is measured, not estimated. Hatching and
gratings can look alike, so a detected stair always carries a confidence below the trust level.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

from keel.extract import Segment

Rung = tuple[float, float, float]  # position across the treads, start and end along them


@dataclass(frozen=True)
class DetectedStair:
    box: tuple[float, float, float, float]
    width: float  # Tread length, in drawing units.
    treads: int
    spacing: float


def _rungs(segments: list[Segment], vertical: bool, tol: float = 0.15) -> list[Rung]:
    rungs: list[Rung] = []
    for s in segments:
        across, along = (abs(s.x1 - s.x0), abs(s.y1 - s.y0)) if vertical else (abs(s.y1 - s.y0), abs(s.x1 - s.x0))
        if along > 0 and across <= tol * along:
            if vertical:
                rungs.append(((s.x0 + s.x1) / 2, min(s.y0, s.y1), max(s.y0, s.y1)))
            else:
                rungs.append(((s.y0 + s.y1) / 2, min(s.x0, s.x1), max(s.x0, s.x1)))
    return sorted(rungs)


def _has_stringers(rails: list[Rung], first: float, last: float, low: float, high: float, reach: float = 0.12) -> bool:
    """rails run across the treads: position along the treads, then their span across the run."""
    span = last - first
    margin = reach * (high - low)

    def covered(edge: float) -> bool:
        total = 0.0
        for position, start, end in rails:
            if abs(position - edge) <= margin:
                total += max(0.0, min(end, last) - max(start, first))
        return total >= 0.6 * span

    return covered(low) and covered(high)


def find_stairs(
    segments: list[Segment],
    width_range: tuple[float, float],
    spacing_range: tuple[float, float],
    min_treads: int = 5,
) -> list[DetectedStair]:
    """width_range and spacing_range are in drawing units, set from the scale."""
    found: list[DetectedStair] = []
    for vertical in (True, False):
        rungs = [r for r in _rungs(segments, vertical) if width_range[0] <= r[2] - r[1] <= width_range[1]]
        rails = _rungs(segments, not vertical)
        used = [False] * len(rungs)
        for i, (position, start, end) in enumerate(rungs):
            if used[i]:
                continue
            run, gaps, current = [i], [], position
            for j in range(i + 1, len(rungs)):
                if used[j]:
                    continue
                other, a, b = rungs[j]
                step = other - current
                if step > spacing_range[1]:
                    break
                if step < spacing_range[0]:
                    continue
                overlap = min(b, end) - max(a, start)
                steady = not gaps or abs(step - statistics.median(gaps)) <= 0.25 * statistics.median(gaps)
                if overlap >= 0.8 * (end - start) and abs((b - a) - (end - start)) <= 0.2 * (end - start) and steady:
                    run.append(j)
                    gaps.append(step)
                    current = other
            if len(run) < min_treads:
                continue
            low, high = min(rungs[k][1] for k in run), max(rungs[k][2] for k in run)
            first, last = rungs[run[0]][0], rungs[run[-1]][0]
            # A stair has a side rail along each end of its treads. Machinery grilles do not.
            if not _has_stringers(rails, first, last, low, high):
                continue
            for k in run:
                used[k] = True
            box = (first, low, last, high) if vertical else (low, first, high, last)
            width = statistics.median(rungs[k][2] - rungs[k][1] for k in run)
            found.append(DetectedStair(box, width, len(run), statistics.median(gaps)))
    return _distinct(found)


def _distinct(stairs: list[DetectedStair]) -> list[DetectedStair]:
    """Both edges of a tread give the same run twice, so overlapping finds are one stair."""
    kept: list[DetectedStair] = []
    for stair in sorted(stairs, key=lambda s: (s.box[2] - s.box[0]) * (s.box[3] - s.box[1]), reverse=True):
        x0, y0, x1, y1 = stair.box
        area = max((x1 - x0) * (y1 - y0), 1e-6)
        overlapped = any(
            max(0.0, min(x1, k.box[2]) - max(x0, k.box[0])) * max(0.0, min(y1, k.box[3]) - max(y0, k.box[1])) > 0.3 * area
            for k in kept
        )
        if not overlapped:
            kept.append(stair)
    return kept
