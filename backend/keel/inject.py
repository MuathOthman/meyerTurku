"""Defect injection. Each function returns a modified copy of the deck.

Meyer's example design is expected to be compliant, so we inject known errors to prove the
checker finds them. Injection works on the ship model, so measurement code runs unchanged.
"""
from __future__ import annotations

from shapely.geometry import LineString, Polygon, box

from keel.checks.common import DOOR_FRAME_ALLOWANCE_MM
from keel.model import Category, Deck, Space


def _copy(deck: Deck, note: str) -> Deck:
    copy = deck.model_copy(deep=True)
    copy.injected = [*copy.injected, note]
    return copy


def _set_polygon(space: Space, polygon) -> None:
    if polygon.geom_type != "Polygon":
        polygon = max(polygon.geoms, key=lambda g: g.area)
    space.exterior_mm = [(x, y) for x, y in polygon.exterior.coords]
    space.interiors_mm = [[(x, y) for x, y in ring.coords] for ring in polygon.interiors]


def _section_at(polygon: Polygon, x: float) -> tuple[float, float]:
    """The longest vertical run of floor at this x."""
    minx, miny, maxx, maxy = polygon.bounds
    cut = LineString([(x, miny - 10), (x, maxy + 10)]).intersection(polygon)
    pieces = list(getattr(cut, "geoms", [cut]))
    longest = max(pieces, key=lambda g: g.length)
    return longest.bounds[1], longest.bounds[3]


def _main_section_x(polygon: Polygon) -> float:
    """A station near mid-length of the corridor, clear of the wider junction areas."""
    minx, _, maxx, _ = polygon.bounds
    return (minx + maxx) / 2


def narrow_corridor(deck: Deck, space_id: str, to_mm: float, length_mm: float = 600.0) -> Deck:
    """Block part of the corridor so the clear width at one station becomes to_mm."""
    result = _copy(deck, f"narrow_corridor:{space_id}:to={to_mm:.0f}mm")
    space = result.space(space_id)
    polygon = space.polygon()
    x = _main_section_x(polygon)
    top, bottom = _section_at(polygon, x)
    if bottom - top <= to_mm:
        raise ValueError(f"{space_id} is already {bottom - top:.0f} mm wide at the injection point")
    obstacle = box(x - length_mm / 2, top - 200, x + length_mm / 2, bottom - to_mm)
    _set_polygon(space, polygon.difference(obstacle))
    return result


def flip_door_swing(deck: Deck, door_id: str) -> Deck:
    """Make the door open the other way, which is Meyer's own example of a costly error."""
    result = _copy(deck, f"flip_door_swing:{door_id}")
    door = result.door(door_id)
    door.swings_into = door.other_side(door.swings_into)
    return result


def remove_exits(deck: Deck, door_ids: list[str]) -> Deck:
    """Delete exit doors, for example to leave a corridor with one means of escape."""
    result = _copy(deck, f"remove_exits:{','.join(door_ids)}")
    result.doors = [d for d in result.doors if d.id not in door_ids]
    return result


def shrink_door(deck: Deck, door_id: str, clear_to_mm: float) -> Deck:
    """Change the door so its estimated clear width becomes clear_to_mm."""
    result = _copy(deck, f"shrink_door:{door_id}:clear={clear_to_mm:.0f}mm")
    result.door(door_id).leaf_width_mm = clear_to_mm + DOOR_FRAME_ALLOWANCE_MM
    return result


def lengthen_dead_end(deck: Deck, space_id: str, spur_mm: float, width_mm: float = 1200.0) -> Deck:
    """Add a corridor spur with one way in, opening off the corridor's south side."""
    result = _copy(deck, f"lengthen_dead_end:{space_id}:spur={spur_mm:.0f}mm")
    space = result.space(space_id)
    polygon = space.polygon()
    x = _main_section_x(polygon)
    _, bottom = _section_at(polygon, x)
    spur = box(x - width_mm / 2, bottom - 100, x + width_mm / 2, bottom + spur_mm)
    _set_polygon(space, polygon.union(spur))
    return result


def add_cabins(deck: Deck, count: int, berths_each: int = 2, near: str | None = None) -> Deck:
    """Add cabins to the persons count. The layout is not redrawn, only the load changes."""
    result = _copy(deck, f"add_cabins:{count}x{berths_each}:near={near}")
    anchor = result.space(near).anchor_mm if near else result.spaces[0].anchor_mm
    x, y = anchor
    for number in range(1, count + 1):
        result.spaces.append(
            Space(
                id=f"NEW-{number:02d}",
                name=f"Added cabin {number}",
                category=Category.CABIN,
                classification_confidence=1.0,
                label_source="injected",
                anchor_mm=anchor,
                exterior_mm=[(x, y), (x + 1, y), (x + 1, y + 1), (x, y + 1)],
                berths=berths_each,
            )
        )
    return result


DEFECTS = {
    "narrow_corridor": lambda deck, a: narrow_corridor(deck, a["id"], a["to_mm"]),
    "flip_door_swing": lambda deck, a: flip_door_swing(deck, a["id"]),
    "remove_exits": lambda deck, a: remove_exits(deck, a["ids"]),
    "shrink_door": lambda deck, a: shrink_door(deck, a["id"], a["to_mm"]),
    "lengthen_dead_end": lambda deck, a: lengthen_dead_end(deck, a["id"], a["spur_mm"]),
    "add_cabins": lambda deck, a: add_cabins(deck, a["count"], a.get("berths_each", 2), a.get("near")),
}


def apply_defect(deck: Deck, name: str, arguments: dict) -> Deck:
    if name not in DEFECTS:
        raise KeyError(f"unknown defect {name!r}. Known: {sorted(DEFECTS)}")
    return DEFECTS[name](deck, arguments)
