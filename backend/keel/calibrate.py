"""Scale calibration from geometry, verified against a second printed dimension.

The printed scale cannot be trusted: the RCRV sheets say 1/8"=1'-0" on a size D
sheet, but the PDF is a shrunk 17x11 in print (0.488 of nominal). So we measure:

  primary: frame ruler tick spacing, against the frame spacing.
           The frame spacing itself comes from printed data: LWL 184'-0" = frames 0..92.
  verify:  moulded beam on the plan, against the printed 41'-0".

The disagreement between the two becomes the scale error used in every verdict.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass

from keel.extract import Primitives, Segment

MM_PER_INCH = 25.4
MM_PER_FOOT = 304.8


def feet_inches_to_mm(feet: float, inches: float = 0.0) -> float:
    return feet * MM_PER_FOOT + inches * MM_PER_INCH


def mm_to_feet_inches(mm: float) -> str:
    """Format for display, e.g. 914.4 -> 3'-0.0"."""
    total = abs(mm) / MM_PER_INCH
    feet = int(total // 12)
    inches = total - feet * 12
    if round(inches, 1) >= 12.0:
        feet, inches = feet + 1, 0.0
    sign = "-" if mm < 0 else ""
    return f"{sign}{feet}'-{inches:.1f}\""


class CalibrationError(ValueError):
    """Raised when scale cannot be established. Never fall back to a guessed scale."""


@dataclass(frozen=True)
class FrameRuler:
    centerline_y: float
    spacing_pt: float
    tick_count: int
    residual_pt: float  # worst tick deviation from the fitted regular grid


@dataclass(frozen=True)
class Calibration:
    mm_per_pt: float
    relative_error: float  # scale disagreement between primary and verifier
    extraction_tolerance_mm: float
    frame_spacing_pt: float
    frame_spacing_mm: float
    beam_measured_pt: float
    beam_expected_mm: float
    beam_measured_mm: float
    ruler_residual_mm: float

    def tolerance_mm(self, length_mm: float) -> float:
        """Total tolerance for a measured length, per the brief's verdict policy."""
        return abs(length_mm) * self.relative_error + self.extraction_tolerance_mm

    def to_mm(self, pt: float) -> float:
        return pt * self.mm_per_pt

    def to_pt(self, mm: float) -> float:
        return mm / self.mm_per_pt


def fit_regular_grid(positions: list[float], spacing_guess: float) -> tuple[float, float]:
    """Least-squares spacing of positions on a regular grid. Returns (spacing, max residual)."""
    if len(positions) < 3:
        raise CalibrationError("need at least 3 positions to fit a grid")
    pts = sorted(positions)
    idx = [round((p - pts[0]) / spacing_guess) for p in pts]
    n = len(pts)
    mean_i, mean_p = sum(idx) / n, sum(pts) / n
    denom = sum((i - mean_i) ** 2 for i in idx)
    if denom == 0:
        raise CalibrationError("positions do not span a grid")
    spacing = sum((i - mean_i) * (p - mean_p) for i, p in zip(idx, pts)) / denom
    offset = mean_p - spacing * mean_i
    residual = max(abs(offset + spacing * i - p) for i, p in zip(idx, pts))
    return spacing, residual


def detect_frame_ruler(
    segments: list[Segment],
    min_ticks: int = 20,
    tick_length_pt: tuple[float, float] = (2.0, 14.0),
) -> FrameRuler:
    """Find the frame ruler: the row of short vertical ticks with the most regular spacing."""
    rows: dict[int, set[float]] = defaultdict(set)
    mids: dict[int, list[float]] = defaultdict(list)
    for s in segments:
        if tick_length_pt[0] < s.length < tick_length_pt[1] and abs(s.x0 - s.x1) < 0.01:
            key = round(s.midpoint[1])
            rows[key].add(round(s.x0, 2))
            mids[key].append(s.midpoint[1])

    best: FrameRuler | None = None
    for key, xs_set in rows.items():
        xs = sorted(xs_set)
        if len(xs) < min_ticks:
            continue
        gaps = [round(b - a, 1) for a, b in zip(xs, xs[1:])]
        modal, modal_count = Counter(gaps).most_common(1)[0]
        if modal < 1.0 or modal_count < 0.5 * len(gaps):
            continue
        run = [
            x
            for i, x in enumerate(xs)
            if (i > 0 and abs(xs[i] - xs[i - 1] - modal) < 0.15)
            or (i < len(xs) - 1 and abs(xs[i + 1] - xs[i] - modal) < 0.15)
        ]
        spacing, residual = fit_regular_grid(run, modal)
        candidate = FrameRuler(sum(mids[key]) / len(mids[key]), spacing, len(run), residual)
        if best is None or candidate.tick_count > best.tick_count:
            best = candidate
    if best is None:
        raise CalibrationError("no frame ruler found")
    return best


def detect_beam_pt(
    segments: list[Segment],
    centerline_y: float,
    min_total_length_pt: float = 300.0,
    symmetry_tol_pt: float = 0.5,
) -> float:
    """Widest pair of long horizontal lines placed symmetrically about the centreline."""
    rows: dict[float, float] = defaultdict(float)
    for s in segments:
        if abs(s.y0 - s.y1) < 0.02:
            rows[round(s.y0, 2)] += s.length
    long_rows = [y for y, length in rows.items() if length >= min_total_length_pt]
    best = 0.0
    for upper in long_rows:
        for lower in long_rows:
            if upper < centerline_y < lower:
                if abs((centerline_y - upper) - (lower - centerline_y)) <= symmetry_tol_pt:
                    best = max(best, lower - upper)
    if best == 0.0:
        raise CalibrationError("no symmetric beam lines found")
    return best


def calibrate(
    primitives: Primitives,
    frame_spacing_mm: float,
    beam_mm: float,
    region: tuple[float, float, float, float] | None = None,
    extraction_tolerance_pt: float = 0.36,
    max_relative_error: float = 0.005,
) -> Calibration:
    """Compute and verify the scale. Refuses if the two references disagree."""
    segments = primitives.segments
    if region is not None:
        x0, y0, x1, y1 = region
        segments = [
            s
            for s in segments
            if x0 <= s.midpoint[0] <= x1 and y0 <= s.midpoint[1] <= y1
        ]
    ruler = detect_frame_ruler(segments)
    mm_per_pt = frame_spacing_mm / ruler.spacing_pt
    beam_pt = detect_beam_pt(segments, ruler.centerline_y)
    beam_measured_mm = beam_pt * mm_per_pt
    relative_error = abs(beam_measured_mm - beam_mm) / beam_mm
    if not math.isfinite(relative_error) or relative_error > max_relative_error:
        raise CalibrationError(
            f"scale verification failed: beam measured {beam_measured_mm:.0f} mm, "
            f"expected {beam_mm:.0f} mm ({relative_error:.2%})"
        )
    return Calibration(
        mm_per_pt=mm_per_pt,
        relative_error=relative_error,
        extraction_tolerance_mm=extraction_tolerance_pt * mm_per_pt,
        frame_spacing_pt=ruler.spacing_pt,
        frame_spacing_mm=frame_spacing_mm,
        beam_measured_pt=beam_pt,
        beam_expected_mm=beam_mm,
        beam_measured_mm=beam_measured_mm,
        ruler_residual_mm=ruler.residual_pt * mm_per_pt,
    )
