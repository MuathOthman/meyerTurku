"""Escape route checks. All numbers come from geometry; all verdicts from keel.verdict."""
from __future__ import annotations

from keel.checks.common import (
    DOOR_FRAME_ALLOWANCE_MM,
    base_finding,
    door_clear_width,
    door_line_pt,
    is_escape_door,
    numeric_why,
    outline_pt,
    to_pt,
)
from keel.geometry import clear_width, dead_end_length, inscribed_diameter, side_of_line, without_thin_obstacles
from keel.graph import EXIT_CATEGORIES, build_graph, escape_path, exit_ids, independent_exit_routes
from keel.model import Category, Deck, Door, Space
from keel.rules import Rule
from keel.verdict import Finding, Verdict, geometric_verdict, numeric_verdict


# A side branch serves few people, and how the width rule applies to it is a judgment call.
BRANCH_APPLICABILITY = 0.5
SHAPE_SOURCE = "shape"
MIN_ROUTE_MM = 500.0
# Whether these class clauses apply depends on facts the drawing does not show.
DISPENSATION_APPLICABILITY = 0.5


def _corridor_width_by_shape(deck: Deck, rule: Rule, space: Space) -> Finding | None:
    """A corridor found from its shape: measure along its own length, end to end.

    Starting from doors would measure into door recesses, which are not the route. Parts
    narrower than the smallest route are left out, so a tail cannot pass as the corridor.
    """
    polygon = space.polygon()
    core = polygon.buffer(-MIN_ROUTE_MM / 2)
    if core.is_empty:
        return None
    part = max(getattr(core, "geoms", [core]), key=lambda g: g.area)
    points = list(part.exterior.coords)
    middle = (part.centroid.x, part.centroid.y)
    first = max(points, key=lambda p: (p[0] - middle[0]) ** 2 + (p[1] - middle[1]) ** 2)
    last = max(points, key=lambda p: (p[0] - first[0]) ** 2 + (p[1] - first[1]) ** 2)
    narrowest = clear_width(polygon, [first, last])
    tolerance = deck.tolerance_mm(narrowest.width_mm)
    verdict = numeric_verdict(
        narrowest.width_mm, rule.value_mm, rule.operator, tolerance,
        classification_confidence=space.classification_confidence,
    )
    return base_finding(
        deck, rule, verdict, space.id, space.name, narrowest.location,
        numeric_why(verdict, "Narrowest clear width along this corridor", narrowest.width_mm, rule.value_mm, tolerance, rule.operator),
        measured_mm=narrowest.width_mm, required_mm=rule.value_mm, tolerance_mm=tolerance,
        assumptions=[
            "This space was read as a corridor from its shape: long, narrow and lined with doors.",
            "Obstacles thinner than 110 mm, such as door symbols and trim, are ignored.",
        ],
        overlay_polygon_pt=outline_pt(deck, space),
    )


def corridor_width(deck: Deck, rule: Rule) -> list[Finding]:
    """Measure the main route between exits, then any narrower branch to a room door.

    The main route can FAIL. A branch is reported with its real measurement, but goes to an
    engineer, since the rule's applicability to a short branch is not certain.
    """
    findings = []
    exits = exit_ids(deck)
    for space in deck.by_category(Category.CORRIDOR):
        if space.label_source == SHAPE_SOURCE:
            finding = _corridor_width_by_shape(deck, rule, space)
            if finding is not None:
                findings.append(finding)
            continue
        doors = [d for d in deck.doors_of(space.id) if is_escape_door(d)]
        exit_doors = [d for d in doors if d.other_side(space.id) in exits]
        route_doors = exit_doors if len(exit_doors) >= 2 else doors
        if len(route_doors) < 2:
            findings.append(
                base_finding(
                    deck, rule, Verdict.NEEDS_REVIEW, space.id, space.name, space.anchor_mm,
                    "Fewer than two doors were found on this corridor, so its through-width cannot be measured.",
                    overlay_polygon_pt=outline_pt(deck, space),
                )
            )
            continue
        assumption = "Obstacles thinner than 110 mm, such as door symbols and trim, are ignored."
        polygon = space.polygon()
        main = clear_width(polygon, [d.midpoint_mm for d in route_doors])
        tolerance = deck.tolerance_mm(main.width_mm)
        verdict = numeric_verdict(
            main.width_mm, rule.value_mm, rule.operator, tolerance,
            classification_confidence=space.classification_confidence,
        )
        findings.append(
            base_finding(
                deck, rule, verdict, space.id, space.name, main.location,
                numeric_why(verdict, "Narrowest clear width on the route between exits", main.width_mm, rule.value_mm, tolerance, rule.operator),
                measured_mm=main.width_mm, required_mm=rule.value_mm, tolerance_mm=tolerance,
                assumptions=[assumption],
                overlay_polygon_pt=outline_pt(deck, space),
            )
        )

        # Doors reached only through something narrower than the main route.
        route_points = [d.midpoint_mm for d in route_doors]
        narrower = []
        pinch = None
        for door in doors:
            if door in route_doors:
                continue
            with_door = clear_width(polygon, route_points + [door.midpoint_mm])
            if with_door.width_mm < main.width_mm - 5.0:
                narrower.append(door)
                if pinch is None or with_door.width_mm < pinch.width_mm:
                    pinch = with_door
        if pinch is None:
            continue
        branch_tolerance = deck.tolerance_mm(pinch.width_mm)
        branch_verdict = numeric_verdict(
            pinch.width_mm, rule.value_mm, rule.operator, branch_tolerance,
            applicability_confidence=BRANCH_APPLICABILITY,
            classification_confidence=space.classification_confidence,
        )
        served = ", ".join(sorted({deck.space(d.other_side(space.id)).name for d in narrower if d.other_side(space.id)}))
        findings.append(
            base_finding(
                deck, rule, branch_verdict, f"{space.id}/branch", f"{space.name} side branch", pinch.location,
                numeric_why(branch_verdict, f"Narrowest clear width on the branch to {served}", pinch.width_mm, rule.value_mm, branch_tolerance, rule.operator),
                measured_mm=pinch.width_mm, required_mm=rule.value_mm, tolerance_mm=branch_tolerance,
                assumptions=[assumption, "Whether this width rule applies to a short branch needs an engineer's judgment."],
                overlay_polygon_pt=outline_pt(deck, space),
            )
        )
    return findings


def stair_width(deck: Deck, rule: Rule) -> list[Finding]:
    findings = []
    for space in deck.by_category(Category.STAIR):
        width, center = inscribed_diameter(without_thin_obstacles(space.polygon()))
        tolerance = deck.tolerance_mm(width)
        verdict = numeric_verdict(
            width, rule.value_mm, rule.operator, tolerance,
            classification_confidence=space.classification_confidence,
        )
        findings.append(
            base_finding(
                deck, rule, verdict, space.id, space.name, center,
                numeric_why(verdict, "Clear stair width", width, rule.value_mm, tolerance, rule.operator),
                measured_mm=width, required_mm=rule.value_mm, tolerance_mm=tolerance,
                assumptions=["Width is the largest circle fitting in the stair enclosure on plan. Handrails are not deducted."],
                overlay_polygon_pt=outline_pt(deck, space),
            )
        )
    return findings


def sole_stair(deck: Deck, rule: Rule) -> list[Finding]:
    """The drawing does not show dispensations, so a shortfall here can only go to an engineer."""
    findings = []
    for space in deck.by_category(Category.STAIR):
        width, center = inscribed_diameter(without_thin_obstacles(space.polygon()))
        tolerance = deck.tolerance_mm(width)
        verdict = numeric_verdict(
            width, rule.value_mm, rule.operator, tolerance,
            applicability_confidence=DISPENSATION_APPLICABILITY,
            classification_confidence=space.classification_confidence,
        )
        findings.append(
            base_finding(
                deck, rule, verdict, space.id, space.name, center,
                numeric_why(verdict, "Clear stair width", width, rule.value_mm, tolerance, rule.operator),
                measured_mm=width, required_mm=rule.value_mm, tolerance_mm=tolerance,
                assumptions=[
                    "Applies only if this stair is a sole means of escape under a dispensation, which the drawing does not show.",
                    "Width is the largest circle fitting in the stair enclosure on plan. Handrails are not deducted.",
                ],
                overlay_polygon_pt=outline_pt(deck, space),
            )
        )
    return findings


def _is_galley_or_laundry(space: Space) -> bool:
    return space.category == Category.GALLEY or "LAUNDRY" in space.name.upper()


def galley_lobby(deck: Deck, rule: Rule) -> list[Finding]:
    """Check what separates a galley or laundry from a stair: nothing, or a space of enough size."""
    findings = []
    assumption = "A fire hose station is also required. Keel cannot see it, so an engineer must confirm it."
    stairs = {s.id for s in deck.by_category(Category.STAIR)}
    seen = set()
    for source in filter(_is_galley_or_laundry, deck.spaces):
        for door in deck.doors_of(source.id):
            between_id = door.other_side(source.id)
            if between_id is None:
                continue
            if between_id in stairs:
                findings.append(
                    base_finding(
                        deck, rule, Verdict.NEEDS_REVIEW, door.id, f"{source.name} to stair", door.midpoint_mm,
                        f"{source.name} opens directly onto a stair, with no lobby between them.",
                        assumptions=[assumption],
                        overlay_polygon_pt=outline_pt(deck, source),
                    )
                )
                continue
            between = deck.space(between_id)
            to_stair = [d for d in deck.doors_of(between_id) if d.other_side(between_id) in stairs]
            if not to_stair or (source.id, between_id) in seen:
                continue
            seen.add((source.id, between_id))
            findings.append(_lobby_finding(deck, rule, source, between, door, to_stair[0], assumption))
    return findings


def _lobby_finding(deck: Deck, rule: Rule, source: Space, lobby: Space, door_in: Door, door_out: Door, assumption: str) -> Finding:
    narrowest = clear_width(lobby.polygon(), [door_in.midpoint_mm, door_out.midpoint_mm])
    tolerance = deck.tolerance_mm(narrowest.width_mm)
    verdict = numeric_verdict(
        narrowest.width_mm, rule.value_mm, rule.operator, tolerance,
        applicability_confidence=DISPENSATION_APPLICABILITY,
        classification_confidence=lobby.classification_confidence,
    )
    why = numeric_why(verdict, f"Clear width from {source.name} to the stair", narrowest.width_mm, rule.value_mm, tolerance, rule.operator)
    why += f" Deck area is {lobby.area_m2:.1f} m2; the rule requires at least {rule.minimum_area_m2:g} m2."
    # Never PASS: the rule also requires a fire hose station, which Keel cannot see.
    if verdict != Verdict.FAIL:
        verdict = Verdict.NEEDS_REVIEW
    if lobby.area_m2 >= rule.minimum_area_m2 and narrowest.width_mm >= rule.value_mm:
        why += " The size is enough, so an engineer should confirm the fire hose station and that this rule applies here."
    return base_finding(
        deck, rule, verdict, f"{source.id}/{lobby.id}", f"{lobby.name}, from {source.name}", narrowest.location, why,
        measured_mm=narrowest.width_mm, required_mm=rule.value_mm, tolerance_mm=tolerance,
        assumptions=[assumption],
        overlay_polygon_pt=outline_pt(deck, lobby),
    )


def stair_capacity(deck: Deck, rule: Rule) -> list[Finding]:
    """W = (N1 + N2) x 10 mm, against the measured width. N2 comes from the deck config."""
    findings = []
    stairs = deck.by_category(Category.STAIR)
    for space in stairs:
        width, center = inscribed_diameter(without_thin_obstacles(space.polygon()))
        persons = deck.total_berths + deck.persons_other_decks
        required = persons * rule.value_mm_per_person / max(1, len(stairs))
        tolerance = deck.tolerance_mm(width)
        verdict = numeric_verdict(
            width, required, rule.operator, tolerance,
            classification_confidence=space.classification_confidence,
        )
        capacity = int(width * max(1, len(stairs)) // rule.value_mm_per_person)
        why = numeric_why(verdict, "Measured stair width", width, required, tolerance, rule.operator)
        findings.append(
            base_finding(
                deck, rule, verdict, space.id, space.name, center,
                f"{why} Serves {persons} persons ({deck.total_berths} on this deck, "
                f"{deck.persons_other_decks} on the adjoining deck); this width carries up to {capacity}.",
                measured_mm=width, required_mm=required, tolerance_mm=tolerance,
                assumptions=[
                    f"{deck.persons_other_decks} persons on the adjoining deck is a config input, not measured.",
                    "Berths per cabin are read from the cabin name.",
                ],
                overlay_polygon_pt=outline_pt(deck, space),
            )
        )
    return findings


def escape_door_width(deck: Deck, rule: Rule) -> list[Finding]:
    """Doors between a corridor and its exits. Clear width is an estimate, stated as such."""
    findings = []
    corridors = {s.id for s in deck.by_category(Category.CORRIDOR)}
    exits = exit_ids(deck)
    for door in deck.doors:
        sides = {door.space_a, door.space_b}
        if not (sides & corridors and sides & exits):
            continue
        # A door the injection tool shrank is a door someone must fit through, whatever its
        # size. Only original small leaves are treated as lockers.
        if not is_escape_door(door) and not any(door.id in i for i in deck.injected):
            continue
        clear = door_clear_width(door)
        tolerance = deck.tolerance_mm(clear)
        verdict = numeric_verdict(clear, rule.value_mm, rule.operator, tolerance)
        findings.append(
            base_finding(
                deck, rule, verdict, door.id, f"Door {door.id}", door.midpoint_mm,
                numeric_why(verdict, "Estimated clear door width", clear, rule.value_mm, tolerance, rule.operator),
                measured_mm=clear, required_mm=rule.value_mm, tolerance_mm=tolerance,
                assumptions=[f"Clear width = leaf width {door.leaf_width_mm:.0f} mm minus {DOOR_FRAME_ALLOWANCE_MM:.0f} mm frame allowance."],
                overlay_lines_pt=[door_line_pt(deck, door)],
            )
        )
    return findings


def _swing_is_with_escape(door: Door, toward_space: str) -> bool:
    return door.swings_into == toward_space


def door_swing(deck: Deck, rule: Rule) -> list[Finding]:
    """Doors on the way from a corridor to its exit must open towards the exit."""
    findings = []
    exits = exit_ids(deck)
    categories = {s.id: s.category for s in deck.spaces}
    names = {s.id: s.name for s in deck.spaces}
    for door in deck.doors:
        if not (door.space_a and door.space_b):
            continue
        # Cabin doors are excepted by SOLAS II-2/13.3.1.5.1, and lockers are not on a route.
        if Category.CABIN in (categories.get(door.space_a), categories.get(door.space_b)):
            continue
        if not is_escape_door(door):
            continue
        pair = {categories.get(door.space_a), categories.get(door.space_b)}
        if Category.CORRIDOR not in pair or not (pair & set(EXIT_CATEGORIES)):
            continue
        toward = door.space_a if door.space_a in exits else door.space_b
        from_space = door.other_side(toward)
        compliant = _swing_is_with_escape(door, toward)
        verdict = geometric_verdict(compliant, 1.0 if door.direction_confident else 0.0)
        route = f"{names[from_space]} to {names[toward]}"
        swings = names.get(door.swings_into, "unknown")
        if verdict == Verdict.PASS:
            why = f"On the escape route {route}, door {door.id} opens towards {swings}, the direction of escape."
        elif verdict == Verdict.FAIL:
            why = f"On the escape route {route}, door {door.id} opens towards {swings}, against the direction of escape."
        else:
            why = f"Door {door.id} is on the route {route}, but its swing could not be read reliably from the drawing."
        findings.append(
            base_finding(
                deck, rule, verdict, door.id, f"Door {door.id}", door.midpoint_mm, why,
                assumptions=["The direction of escape runs from the corridor to the stair enclosure or open deck."],
                overlay_lines_pt=[
                    door_line_pt(deck, door),
                    [to_pt(deck, door.hinge_mm), to_pt(deck, door.arc_mid_mm)],
                ],
            )
        )
    return findings


def two_means(deck: Deck, rule: Rule) -> list[Finding]:
    """Each corridor needs routes to at least the required number of different exits."""
    findings = []
    exits = exit_ids(deck)
    # An escape route runs through circulation spaces, not through cabins or a hospital.
    circulation = {s.id for s in deck.by_category(Category.CORRIDOR, *EXIT_CATEGORIES)}
    graph = build_graph(
        deck,
        include_door=lambda d: is_escape_door(d) and d.space_a in circulation and d.space_b in circulation,
    )
    names = {s.id: s.name for s in deck.spaces}
    for space in deck.by_category(Category.CORRIDOR):
        reached = independent_exit_routes(graph, space.id, exits)
        compliant = len(reached) >= rule.minimum_routes
        verdict = geometric_verdict(compliant, classification_confidence=space.classification_confidence)
        listing = ", ".join(names[e] for e in reached) or "none"
        findings.append(
            base_finding(
                deck, rule, verdict, space.id, space.name, space.anchor_mm,
                f"{len(reached)} independent exit route(s) found, {rule.minimum_routes} required. Reached: {listing}.",
                assumptions=["Exits on this drawing are stair enclosures and the open deck. Routes through cabins or rooms do not count."],
                overlay_polygon_pt=outline_pt(deck, space),
            )
        )
    return findings


def dead_end(deck: Deck, rule: Rule) -> list[Finding]:
    findings = []
    for space in deck.by_category(Category.CORRIDOR):
        exit_doors = [
            d.midpoint_mm
            for d in deck.doors_of(space.id)
            if is_escape_door(d) and d.other_side(space.id) in exit_ids(deck)
        ]
        if not exit_doors:
            findings.append(
                base_finding(
                    deck, rule, Verdict.NEEDS_REVIEW, space.id, space.name, space.anchor_mm,
                    "No exit door found on this corridor, so its dead-end length cannot be measured.",
                    overlay_polygon_pt=outline_pt(deck, space),
                )
            )
            continue
        cell_mm = 100.0
        result = dead_end_length(space.polygon(), exit_doors, cell_mm=cell_mm)
        tolerance = deck.tolerance_mm(result.length_mm) + cell_mm
        verdict = numeric_verdict(
            result.length_mm, rule.value_mm, rule.operator, tolerance,
            classification_confidence=space.classification_confidence,
        )
        findings.append(
            base_finding(
                deck, rule, verdict, space.id, space.name, result.tip,
                numeric_why(verdict, "Longest dead-end walk from the through-route", result.length_mm, rule.value_mm, tolerance, rule.operator),
                measured_mm=result.length_mm, required_mm=rule.value_mm, tolerance_mm=tolerance,
                assumptions=[f"Walking distance on a {cell_mm:.0f} mm grid; the local width is subtracted (recess exception)."],
                overlay_polygon_pt=outline_pt(deck, space),
            )
        )
    return findings


__all__ = [
    "corridor_width",
    "dead_end",
    "door_swing",
    "escape_door_width",
    "stair_capacity",
    "stair_width",
    "two_means",
    "escape_path",
    "side_of_line",
]
