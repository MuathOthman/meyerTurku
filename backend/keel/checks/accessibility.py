"""ADA checks. They run only on spaces an engineer has marked accessible.

The drawing does not show which routes are accessible. A guess could fail a whole ship
against a standard it was not designed to, so these rules are opt-in per space.
"""
from __future__ import annotations

from keel.checks.common import (
    DOOR_FRAME_ALLOWANCE_MM,
    base_finding,
    door_clear_width,
    door_line_pt,
    is_escape_door,
    numeric_why,
    outline_pt,
)
from keel.geometry import clear_width, inscribed_diameter, without_thin_obstacles
from keel.model import Deck
from keel.rules import Rule
from keel.verdict import Finding, Verdict, numeric_verdict


def accessible_door(deck: Deck, rule: Rule) -> list[Finding]:
    findings = []
    for space in (s for s in deck.spaces if s.accessible):
        for door in deck.doors_of(space.id):
            if not is_escape_door(door):
                continue
            clear = door_clear_width(door)
            tolerance = deck.tolerance_mm(clear)
            verdict = numeric_verdict(clear, rule.value_mm, rule.operator, tolerance)
            findings.append(
                base_finding(
                    deck, rule, verdict, door.id, f"Door {door.id} of {space.name}", door.midpoint_mm,
                    numeric_why(verdict, "Estimated clear door width", clear, rule.value_mm, tolerance, rule.operator),
                    measured_mm=clear, required_mm=rule.value_mm, tolerance_mm=tolerance,
                    assumptions=[f"Clear width = leaf width {door.leaf_width_mm:.0f} mm minus {DOOR_FRAME_ALLOWANCE_MM:.0f} mm frame allowance."],
                    overlay_lines_pt=[door_line_pt(deck, door)],
                )
            )
    return findings


def accessible_route(deck: Deck, rule: Rule) -> list[Finding]:
    findings = []
    for space in (s for s in deck.spaces if s.accessible):
        terminals = [d.midpoint_mm for d in deck.doors_of(space.id) if is_escape_door(d)]
        if len(terminals) < 2:
            continue
        result = clear_width(space.polygon(), terminals)
        tolerance = deck.tolerance_mm(result.width_mm)
        verdict = numeric_verdict(result.width_mm, rule.value_mm, rule.operator, tolerance)
        findings.append(
            base_finding(
                deck, rule, verdict, space.id, space.name, result.location,
                numeric_why(verdict, "Narrowest clear width", result.width_mm, rule.value_mm, tolerance, rule.operator),
                measured_mm=result.width_mm, required_mm=rule.value_mm, tolerance_mm=tolerance,
                overlay_polygon_pt=outline_pt(deck, space),
            )
        )
    return findings


def accessible_turning(deck: Deck, rule: Rule) -> list[Finding]:
    findings = []
    for space in (s for s in deck.spaces if s.accessible):
        diameter, center = inscribed_diameter(without_thin_obstacles(space.polygon()))
        tolerance = deck.tolerance_mm(diameter)
        # The T-shaped alternative is not tested, so a shortfall is never an automatic fail.
        verdict = numeric_verdict(diameter, rule.value_mm, rule.operator, tolerance, applicability_confidence=0.5)
        findings.append(
            base_finding(
                deck, rule, verdict, space.id, space.name, center,
                numeric_why(verdict, "Largest clear circle", diameter, rule.value_mm, tolerance, rule.operator),
                measured_mm=diameter, required_mm=rule.value_mm, tolerance_mm=tolerance,
                assumptions=["Furniture on the drawing counts as an obstruction."],
                overlay_polygon_pt=outline_pt(deck, space),
            )
        )
    return findings


__all__ = ["accessible_door", "accessible_route", "accessible_turning", "Verdict"]
