"""Escape from machinery spaces on cargo ships, SOLAS II-2/13.4.2.

Stairs are found from their drawn treads and doors from their swing arcs. A vertical ladder
narrower than 500 mm is not found, so a missing route only ever goes to an engineer.
"""
from __future__ import annotations

import math
import re

from keel.checks.common import base_finding, door_line_pt, is_escape_door, numeric_why, outline_pt, to_pt
from keel.geometry import dead_end_length
from keel.model import Category, Deck, Space
from keel.rules import Rule
from keel.verdict import Finding, Verdict, numeric_verdict

CATEGORY_A = re.compile(r"ENGINE\s*ROOM", re.IGNORECASE)
NOT_CATEGORY_A = re.compile(r"VENTILATION|CONTROL|CASING", re.IGNORECASE)
# Casings, trunks, ducts and tanks are not rooms anyone works in.
NOT_A_ROOM = re.compile(r"CASING|TRUNK|UPTAKE|DUCT|TANK|TK\b|VOID|SHAFT", re.IGNORECASE)  # TK: "SETLTK.", "DAY TK."
NEAR_MM = 300.0
# Whether a space is category A, or entered only occasionally, is an engineer's call.
APPLICABILITY = 0.5
# AI names confirmed by OCR are capped at 0.75; unconfirmed guesses at 0.4.
PRINTED_NAME = 0.5
LADDER_NOTE = "Keel finds stairs from their drawn treads. A vertical ladder narrower than 500 mm is not found."


def _named_machinery(deck: Deck) -> list[Space]:
    """Machinery spaces whose name is printed on the drawing. An AI guess from symbols, such as
    "deck machinery / equipment", is often a winch on open deck, not a room to escape from."""
    return [s for s in deck.by_category(Category.MACHINERY) if s.classification_confidence >= PRINTED_NAME]


def is_category_a(space: Space) -> bool:
    return bool(CATEGORY_A.search(space.name)) and not NOT_CATEGORY_A.search(space.name)


def _routes(deck: Deck, space: Space) -> tuple[list[Space], list]:
    """Stairs inside or touching the space, and doors from it to another space."""
    reach = space.polygon().buffer(NEAR_MM)
    stairs = [s for s in deck.by_category(Category.STAIR) if s.id != space.id and s.polygon().intersects(reach)]
    doors = [d for d in deck.doors_of(space.id) if is_escape_door(d) and d.other_side(space.id)]
    return stairs, doors


def _centre(space: Space) -> tuple[float, float]:
    point = space.polygon().centroid
    return (point.x, point.y)


def machinery_a_escape(deck: Deck, rule: Rule) -> list[Finding]:
    """13.4.2.1: two ladders as widely separated as possible, or one ladder and a lower door."""
    findings = []
    for space in _named_machinery(deck):
        if not is_category_a(space):
            continue
        stairs, doors = _routes(deck, space)
        lines = []
        separation = 0.0
        for i, a in enumerate(stairs):
            for b in stairs[i + 1 :]:
                distance = math.dist(_centre(a), _centre(b))
                if distance > separation:
                    separation = distance
                    lines = [[to_pt(deck, _centre(a)), to_pt(deck, _centre(b))]]
        compliant = len(stairs) >= 2 or (len(stairs) >= 1 and len(doors) >= 1)
        found = f"{len(stairs)} stair(s) and {len(doors)} door(s) to other spaces found"
        if compliant:
            verdict = Verdict.PASS
            why = f"{found}, so two means of escape are drawn."
            if len(stairs) >= 2:
                why += f" The two farthest stairs are {separation / 1000:.1f} m apart; an engineer judges whether that is widely separated."
        else:
            verdict = Verdict.NEEDS_REVIEW
            why = f"{found}; two means of escape are required. A ladder may be drawn that Keel cannot see, so an engineer should check."
        findings.append(
            base_finding(
                deck, rule, verdict, space.id, space.name, space.anchor_mm, why,
                assumptions=[
                    "Read as a machinery space of category A from its name. An engineer confirms the category.",
                    LADDER_NOTE,
                    "One ladder within a protected enclosure of at least 800 x 800 mm is also required. Keel does not check the enclosure.",
                ],
                overlay_polygon_pt=outline_pt(deck, space),
                overlay_lines_pt=lines + [door_line_pt(deck, d) for d in doors],
            )
        )
    return findings


def machinery_other_escape(deck: Deck, rule: Rule) -> list[Finding]:
    """13.4.2.3: two escape routes, or one if the walk to the door is at most 5 m."""
    findings = []
    for space in _named_machinery(deck):
        if is_category_a(space) or NOT_A_ROOM.search(space.name):
            continue
        stairs, doors = _routes(deck, space)
        routes = len(stairs) + len(doors)
        assumptions = [
            "A single route is also accepted for a space entered only occasionally, which Keel cannot know.",
            LADDER_NOTE,
        ]
        if routes >= 2:
            findings.append(
                base_finding(
                    deck, rule, Verdict.PASS, space.id, space.name, space.anchor_mm,
                    f"{len(doors)} door(s) and {len(stairs)} stair(s) lead out of this space, so it has two escape routes.",
                    assumptions=assumptions,
                    overlay_polygon_pt=outline_pt(deck, space),
                    overlay_lines_pt=[door_line_pt(deck, d) for d in doors],
                )
            )
            continue
        if not doors:
            findings.append(
                base_finding(
                    deck, rule, Verdict.NEEDS_REVIEW, space.id, space.name, space.anchor_mm,
                    "No door was found on this space, so its escape routes cannot be counted.",
                    assumptions=assumptions,
                    overlay_polygon_pt=outline_pt(deck, space),
                )
            )
            continue
        door = doors[0]
        cell_mm = 100.0
        try:
            walk = dead_end_length(space.polygon(), [door.midpoint_mm], cell_mm=cell_mm, recess_allowance=False)
        except ValueError:
            continue
        tolerance = deck.tolerance_mm(walk.length_mm) + cell_mm
        verdict = numeric_verdict(
            walk.length_mm, rule.value_mm, rule.operator, tolerance,
            applicability_confidence=APPLICABILITY,
            classification_confidence=space.classification_confidence,
        )
        why = numeric_why(verdict, "One escape route. The longest walk to its door", walk.length_mm, rule.value_mm, tolerance, rule.operator)
        findings.append(
            base_finding(
                deck, rule, verdict, space.id, space.name, walk.tip, why,
                measured_mm=walk.length_mm, required_mm=rule.value_mm, tolerance_mm=tolerance,
                assumptions=[f"Walking distance on a {cell_mm:.0f} mm grid, around furniture thicker than 110 mm.", *assumptions],
                overlay_polygon_pt=outline_pt(deck, space),
                overlay_lines_pt=[door_line_pt(deck, door), [to_pt(deck, door.midpoint_mm), to_pt(deck, walk.tip)]],
            )
        )
    return findings
