"""Shared helpers that turn a measurement into a Finding with full evidence."""
from __future__ import annotations

from keel.calibrate import mm_to_feet_inches
from keel.model import Deck, Door, PointMM, Space
from keel.rules import Rule
from keel.verdict import Finding, Verdict, margin_mm

# The drawing does not dimension door stops. Clear width = leaf width minus this allowance.
DOOR_FRAME_ALLOWANCE_MM = 50.0
# Smaller leaves are lockers and panels, not doors people escape through.
MIN_ESCAPE_DOOR_LEAF_MM = 600.0


def door_clear_width(door: Door) -> float:
    return door.leaf_width_mm - DOOR_FRAME_ALLOWANCE_MM


def is_escape_door(door: Door) -> bool:
    return door.leaf_width_mm >= MIN_ESCAPE_DOOR_LEAF_MM


def display(mm: float) -> str:
    """Both unit systems, because the source drawings are American."""
    return f"{mm:.0f} mm ({mm_to_feet_inches(mm)})"


def to_pt(deck: Deck, point: PointMM) -> tuple[float, float]:
    return (point[0] / deck.mm_per_pt, point[1] / deck.mm_per_pt)


def outline_pt(deck: Deck, space: Space) -> list[tuple[float, float]]:
    return [to_pt(deck, p) for p in space.exterior_mm]


def door_line_pt(deck: Deck, door: Door) -> list[tuple[float, float]]:
    return [to_pt(deck, door.hinge_mm), to_pt(deck, door.latch_mm)]


def base_finding(
    deck: Deck,
    rule: Rule,
    verdict: Verdict,
    subject_id: str,
    subject_name: str,
    location: PointMM,
    why: str,
    measured_mm: float | None = None,
    required_mm: float | None = None,
    tolerance_mm: float | None = None,
    assumptions: list[str] | None = None,
    overlay_polygon_pt: list[tuple[float, float]] | None = None,
    overlay_lines_pt: list[list[tuple[float, float]]] | None = None,
) -> Finding:
    has_numbers = measured_mm is not None and required_mm is not None and rule.operator
    margin = margin_mm(measured_mm, required_mm, rule.operator) if has_numbers else None
    # Advice only where it applies: a shortfall with numbers, or a yes/no rule with no numbers in its text.
    fix = ""
    if verdict != Verdict.PASS and subject_id != "deck":
        if margin is not None:
            fix = rule.fix.format(shortfall=f"{abs(margin):.0f}", required=f"{required_mm:.0f}")
        elif "{" not in rule.fix:
            fix = rule.fix
    return Finding(
        why_it_matters=rule.why_it_matters,
        fix=fix,
        rule_id=rule.id,
        rule_title=rule.title,
        source=rule.source,
        ref_url=rule.ref_url,
        value_status=rule.value_status,
        verdict=verdict,
        subject_id=subject_id,
        subject_name=subject_name,
        source_pdf=deck.source_pdf,
        page_index=deck.page_index,
        location_mm=location,
        location_pt=to_pt(deck, location),
        measured_mm=measured_mm,
        measured_display=display(measured_mm) if measured_mm is not None else "",
        required_mm=required_mm,
        required_display=display(required_mm) if required_mm is not None else "",
        operator=rule.operator or "",
        tolerance_mm=tolerance_mm,
        margin_mm=margin,
        why=why,
        interpretation_note=rule.interpretation_note,
        assumptions=assumptions or [],
        overlay_polygon_pt=overlay_polygon_pt or [],
        overlay_lines_pt=overlay_lines_pt or [],
    )


def numeric_why(verdict: Verdict, what: str, measured: float, required: float, tolerance: float, operator: str) -> str:
    relation = "at least" if operator == ">=" else "at most"
    head = f"{what} is {display(measured)}; the rule requires {relation} {display(required)}"
    if verdict == Verdict.PASS:
        return f"{head}. Met by more than the {tolerance:.0f} mm tolerance."
    if verdict == Verdict.FAIL:
        return f"{head}. Violated by more than the {tolerance:.0f} mm tolerance."
    gap = measured - required if operator == ">=" else required - measured
    if abs(gap) <= tolerance:
        return f"{head}. The difference is within the {tolerance:.0f} mm tolerance, so an engineer should decide."
    if gap < 0:
        return (
            f"{head}. It misses by {abs(gap):.0f} mm, more than the {tolerance:.0f} mm tolerance, but "
            "whether the rule applies here is uncertain, so an engineer should decide."
        )
    return f"{head}. Confidence in this result is low, so an engineer should decide."
