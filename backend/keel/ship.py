"""Whole-ship checks: what one deck plan cannot tell.

Two kinds, both deterministic:
  Values this ship must meet: limits worked out from the main dimensions printed on the sheet.
  Spaces the rules need: is the space a regulation needs shown on any deck, and where.

Nothing here passes or fails a ship. A missing label may only mean the space is on another
drawing, so every item says what was found and leaves the decision to an engineer.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pymupdf

# Title block rows, matched on the words to the left of each value.
PARTICULARS = {
    "length_overall_m": re.compile(r"LENGTH\s+O\.?\s*A", re.I),
    "length_pp_m": re.compile(r"LENGTH\s+P\.?\s*P", re.I),
    "breadth_m": re.compile(r"^BREADTH", re.I),
    "frame_spacing_mm": re.compile(r"^FRAME\s+SPACING", re.I),
}
NUMBER = re.compile(r"^\d+(?:[.,]\d+)?$")


@dataclass
class Particulars:
    length_overall_m: float | None = None
    length_pp_m: float | None = None
    breadth_m: float | None = None
    frame_spacing_mm: float | None = None
    title: str = ""


def read_particulars(path: str | Path, page: int = 0) -> Particulars:
    """Main dimensions from the sheet's text layer. A value missing on the sheet stays None."""
    found = Particulars()
    try:
        with pymupdf.open(path) as document:
            words = document[page].get_text("words")
            found.title = " ".join(
                b[4].split("\n")[0].strip() for b in document[page].get_text("blocks")
                if re.search(r"\bVESSEL\b|\bSHIP\b", b[4], re.I) and len(b[4]) < 120
            )[:120]
    except (RuntimeError, ValueError, IndexError):
        return found
    rows: dict[int, list] = {}
    for w in words:
        rows.setdefault(round(w[1]), []).append(w)
    numbers = [w for w in words if NUMBER.match(w[4])]
    for top, row in rows.items():
        label = " ".join(w[4] for w in sorted(row, key=lambda w: w[0]) if not NUMBER.match(w[4]))
        right = max(w[2] for w in row)
        for key, pattern in PARTICULARS.items():
            if getattr(found, key) is not None or not pattern.search(label):
                continue
            # The value sits to the right, its top within the label's row height.
            height = max(w[3] - w[1] for w in row)
            candidates = [n for n in numbers if n[0] > right and top - 2 <= n[1] <= top + height and n[0] - right < 600]
            if candidates:
                value = min(candidates, key=lambda n: n[0])[4].replace(",", ".")
                setattr(found, key, float(value))
    return found


@dataclass
class ShipItem:
    regulation: str  # The convention or code, as the engineer's list names it.
    ref: str
    title: str
    status: str  # value | shown | not_shown | by_hand | not_applicable
    detail: str
    where: list[dict] = field(default_factory=list)  # {analysis, deck, space, number}


def colreg_values(p: Particulars) -> list[ShipItem]:
    """COLREG limits for a power-driven vessel, worked out from length overall and breadth."""
    length, breadth = p.length_overall_m, p.breadth_m
    if length is None:
        return [ShipItem("COLREG", "Rule 3(j), Annex I", "Lights and their positions", "by_hand",
                         "Length overall was not found on the sheet, so the limits could not be worked out.")]
    items = []
    if length >= 50:
        items.append(ShipItem(
            "COLREG", "Rule 23(a)(ii)", "Second masthead light", "value",
            f"Length overall is {length:g} m, 50 m or more, so a second masthead light abaft of and higher than the forward one is required.",
        ))
        items.append(ShipItem(
            "COLREG", "Annex I 3(a)", "Horizontal distance between masthead lights", "value",
            f"At least {min(length / 2, 100):g} m apart (half of {length:g} m). The forward light no more than {length / 4:g} m from the stem.",
        ))
        items.append(ShipItem(
            "COLREG", "Annex I 2(a)(ii)", "Height of the after masthead light", "value",
            "At least 4.5 m vertically higher than the forward masthead light.",
        ))
    if length >= 20:
        if breadth is None:
            height = "at least 6 m above the hull, and at least the breadth if that is more (breadth not found on the sheet)"
        else:
            needed = min(max(6.0, breadth), 12.0)
            height = f"at least {needed:g} m above the hull (breadth {breadth:g} m; the rule never asks for more than 12 m)"
        items.append(ShipItem("COLREG", "Annex I 2(a)(i)", "Height of the forward masthead light", "value", f"The forward masthead light {height}."))
    if length >= 50:
        items.append(ShipItem(
            "COLREG", "Rule 22(a)", "Visibility of lights", "value",
            "Masthead light 6 miles. Sidelights, sternlight, towing light and all-round lights 3 miles.",
        ))
    items.append(ShipItem(
        "COLREG", "Rule 26", "Trawling lights", "by_hand",
        "When trawling, a fishing vessel shows all-round green over white lights. Whether research trawling counts as fishing is for the engineer and flag to decide.",
    ))
    for item in items:
        if item.ref.startswith("Annex I"):
            item.detail += " Measure on the profile drawing. Heights are above the uppermost continuous deck."
    return items


@dataclass(frozen=True)
class Needed:
    regulation: str
    ref: str
    title: str
    pattern: re.Pattern
    why: str


NEEDED = [
    Needed("MARPOL", "Annex IV reg. 9", "Sewage system", re.compile(r"SEWAGE|\bSTP\b|BLACK\s*WATER|HOLDING\s*TANK", re.I),
           "Ships of 400 GT and above, or certified for more than 15 persons, need an approved sewage treatment plant, comminuting system or holding tank."),
    Needed("MARPOL", "Annex I reg. 12", "Oil residue (sludge) tank", re.compile(r"SLUDGE|OIL\s*RESIDUE|BILGE", re.I),
           "Ships of 400 GT and above need a tank for oil residue. A bilge or settling tank label is a lead, not proof."),
    Needed("MARPOL", "Annex I reg. 14", "Oil filtering equipment (15 ppm)", re.compile(r"OILY\s*WATER|\bOWS\b|SEPARATOR|15\s*PPM", re.I),
           "Ships of 400 GT and above need oil filtering equipment. It is often only on the engine room arrangement."),
    Needed("MARPOL", "Annex V reg. 10", "Garbage handling", re.compile(r"GARBAGE|COMPACTOR|INCINERATOR|WASTE", re.I),
           "Ships of 100 GT and above need a garbage management plan; a garbage store and compactor support it."),
    Needed("Ballast Water Convention", "Reg. B-3 and D-2", "Ballast water management system", re.compile(r"BALLAST|\bBWTS\b|\bBWMS\b|\bBW\b", re.I),
           "A ship that carries ballast water must meet the D-2 discharge standard, normally with a type-approved treatment system."),
    Needed("SOLAS", "II-1/43", "Emergency source of electrical power", re.compile(r"EMERG\w*\.?\s*GEN|EMERGENCY\s*SWITCH", re.I),
           "Cargo ships: above the uppermost continuous deck, readily reached from the open deck, outside machinery casings and aft of the collision bulkhead."),
    Needed("SOLAS", "II-1/29", "Steering gear compartment", re.compile(r"STEERING", re.I),
           "Readily accessible and, as far as practicable, separated from machinery spaces."),
    Needed("SOLAS", "III/31", "Survival craft and rescue boat", re.compile(r"LIFE\s*BOAT|LIFE\s*RAFT|RESCUE\s*BOAT|SURVIVAL\s*CRAFT|DAVIT", re.I),
           "Cargo ships carry survival craft on each side for everyone on board, and a rescue boat. These are often drawn as symbols without a label."),
    Needed("SOLAS", "II-2/13.4.2", "Emergency exit from the lower spaces", re.compile(r"EM\w*\.?\s*EXIT|ESCAPE\s*TRUNK", re.I),
           "An escape trunk or emergency exit is usually the second way out of the lowest spaces."),
]


def spaces_needed(analyses: list[dict]) -> list[ShipItem]:
    """For each space a regulation needs, the decks and rooms whose names match it."""
    items = []
    for need in NEEDED:
        # Tanks and equipment are set aside as "not a room", but still count as shown on the
        # drawing: a "BILGE SETTL. TANK" label is evidence for MARPOL all the same.
        where = [
            {"analysis": a["id"], "deck": a.get("deck") or a.get("source", ""), "space": s["name"], "number": s["number"]}
            for a in analyses
            for s in a.get("spaces", [])
            if s.get("name_on_drawing") and need.pattern.search(s["name"])
        ] + [
            {"analysis": a["id"], "deck": a.get("deck") or a.get("source", ""), "space": s["description"], "number": s["number"]}
            for a in analyses
            for s in a.get("set_aside", [])
            if s.get("reason", "").startswith(("Tank", "Equipment")) and need.pattern.search(s.get("description", ""))
        ]
        if where:
            decks = sorted({w["deck"] for w in where})
            names = sorted({w["space"] for w in where})
            detail = f"Shown as {', '.join(names)} on {', '.join(decks)}. {need.why}"
            items.append(ShipItem(need.regulation, need.ref, need.title, "shown", detail, where))
        else:
            detail = f"No label for this was found on the checked decks. It may be on another drawing. {need.why}"
            items.append(ShipItem(need.regulation, need.ref, need.title, "not_shown", detail))
    return items


BY_HAND = [
    ShipItem("Load Line Convention", "Reg. 25", "Guard rails and bulwarks", "by_hand",
             "At least 1 m high on exposed decks. Needs the profile and sections, not a plan."),
    ShipItem("Load Line Convention", "Reg. 39", "Minimum bow height and reserve buoyancy", "by_hand",
             "Worked out from length, block coefficient and freeboard, which a GA plan does not give."),
    ShipItem("SOLAS", "Chapter XIV, Polar Code", "Operation in polar waters", "by_hand",
             "The title names Arctic operation. The Polar Code then adds requirements for structure, escape, survival equipment and a Polar Ship Certificate."),
    ShipItem("DNV class rules", "DNV-RU-SHIP", "Class rules for this ship type", "by_hand",
             "Keel's DNV rules are written for passenger ships. Check the current class rules for a research vessel with the class society."),
]


def not_applicable(ship_type: str) -> list[ShipItem]:
    if ship_type == "passenger":
        return []
    return [
        ShipItem("ADA", "2010 Standards", "Accessibility", "not_applicable",
                 "Keel applies ADA to passenger ships only. This project is a cargo or research ship."),
        ShipItem("PVAG", "Proposed 2013 guidelines", "Passenger vessel accessibility", "not_applicable",
                 "Written for passenger vessels. This project is a cargo or research ship."),
    ]


def ship_checks(analyses: list[dict], particulars: Particulars, ship_type: str) -> dict:
    items = colreg_values(particulars) + spaces_needed(analyses) + BY_HAND + not_applicable(ship_type)
    return {
        "particulars": asdict(particulars),
        "decks": [{"analysis": a["id"], "deck": a.get("deck") or a.get("source", "")} for a in analyses],
        "items": [asdict(i) for i in items],
    }
