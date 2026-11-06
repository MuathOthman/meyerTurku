"""PDF + deck config -> ship model. This connects extraction, rooms, doors and labels."""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

import yaml
from shapely import STRtree
from shapely.geometry import Polygon

from keel.calibrate import calibrate, feet_inches_to_mm
from keel.classify import classify
from keel.doors import DetectedDoor, doors_from_arcs, find_door_arcs
from keel.extract import extract_pdf_page
from keel.geometry import side_of_line
from keel.labels import group_blocks, place_labels, render_text_layer, run_ocr
from keel.llm import LLM
from keel.model import Category, Deck, Door, Space
from keel.rooms import (
    build_wall_lines,
    cell_at,
    cell_near,
    detect_leader_dots,
    find_leader_lines,
    free_cells,
)

MIN_ROOM_AREA_PT2 = 40.0  # About 0.2 m2. Smaller cells are slivers inside symbols.
OCR_SCALE = 6.0


@dataclass
class LabelReport:
    """How OCR alone compares with the engineer-reviewed labels."""

    reviewed: int = 0
    ocr_name_correct: int = 0
    ocr_compartment_correct: int = 0


def _in_region(point, region) -> bool:
    return region[0] <= point[0] <= region[2] and region[1] <= point[1] <= region[3]


def _polygon_mm(cell: Polygon, mm_per_pt: float) -> tuple[list, list]:
    simple = cell.simplify(0.02)
    if simple.geom_type != "Polygon" or simple.is_empty:
        simple = cell
    exterior = [(x * mm_per_pt, y * mm_per_pt) for x, y in simple.exterior.coords]
    interiors = [[(x * mm_per_pt, y * mm_per_pt) for x, y in ring.coords] for ring in simple.interiors]
    return exterior, interiors


def _door_side_cell(cells, tree, door: DetectedDoor, sign: float) -> Polygon | None:
    """The first real room on one side of the door, stepping away from the opening."""
    mid = ((door.hinge[0] + door.latch[0]) / 2, (door.hinge[1] + door.latch[1]) / 2)
    dx, dy = door.latch[0] - door.hinge[0], door.latch[1] - door.hinge[1]
    length = (dx * dx + dy * dy) ** 0.5
    nx, ny = -dy / length * sign, dx / length * sign
    for along in (0.0, 0.25, -0.25):
        start = (mid[0] + dx * along, mid[1] + dy * along)
        for offset in (1.0, 2.0, 3.0, 4.5, 6.0, 8.0):
            cell = cell_at(cells, tree, (start[0] + nx * offset, start[1] + ny * offset))
            if cell is not None and cell.area >= MIN_ROOM_AREA_PT2:
                return cell
    return None


def _ocr_labels(primitives, config, dots):
    region = tuple(config["label_region"])
    segments = [s for s in primitives.segments if _in_region(s.midpoint, region)]
    curves = [c for c in primitives.curves if _in_region(c.p0, region)]
    image = render_text_layer(segments, curves, region, scale=OCR_SCALE)
    blocks = group_blocks(run_ocr(image, region, OCR_SCALE))
    return place_labels(blocks, dots, primitives.segments)


def _reviewed_or_ocr(config, placed_ocr, llm):
    """Entries of (anchor, name, compartment, category, confidence, source, berths, accessible)."""
    reviewed = config.get("reviewed_labels") or []
    if reviewed:
        return [
            {
                "anchor": tuple(e["anchor"]),
                "name": e["name"],
                "compartment": e.get("compartment"),
                "category": Category(e["category"]),
                "confidence": 1.0,
                "source": "reviewed",
                "berths": e.get("berths", 0),
                "accessible": e.get("accessible", False),
            }
            for e in reviewed
        ]
    names = sorted({p.block.name for p in placed_ocr if p.block.name})
    categories = classify(names, llm)
    entries = []
    for placed in placed_ocr:
        name = placed.block.name
        if not name:
            continue
        category, confidence = categories.get(name, (Category.UNKNOWN, 0.0))
        entries.append(
            {
                "anchor": placed.anchor,
                "name": name,
                "compartment": placed.block.compartment,
                "category": category,
                "confidence": min(confidence, placed.block.confidence),
                "source": f"ocr_{placed.via}",
                "berths": 2 if category == Category.CABIN else 0,
                "accessible": False,
            }
        )
    return entries


def _compare_labels(config, placed_ocr, cells, tree) -> LabelReport:
    """Score unassisted OCR and leader tracing against the reviewed table."""
    report = LabelReport()
    by_cell: dict[int, list] = {}
    for placed in placed_ocr:
        cell = cell_near(cells, tree, placed.anchor)
        if cell is not None:
            by_cell.setdefault(id(cell), []).append(placed)
    for entry in config.get("reviewed_labels") or []:
        report.reviewed += 1
        cell = cell_near(cells, tree, tuple(entry["anchor"]))
        candidates = by_cell.get(id(cell), []) if cell is not None else []
        compact = entry["name"].replace(" ", "").upper()
        if any(
            SequenceMatcher(None, c.block.name.replace(" ", "").upper(), compact).ratio() >= 0.85
            for c in candidates
        ):
            report.ocr_name_correct += 1
        wanted = entry.get("compartment")
        if wanted and any(c.block.compartment == wanted for c in candidates):
            report.ocr_compartment_correct += 1
    return report


def build_deck(config_path: str | Path, llm: LLM | None = None) -> tuple[Deck, LabelReport]:
    config_path = Path(config_path)
    config = yaml.safe_load(config_path.read_text())
    root = config_path.parent
    pdf_path = (root / config["pdf"]).resolve()
    page_index = config["page_index"]
    region = tuple(config["plan_region"])
    primitives = extract_pdf_page(pdf_path, page_index)

    cal_config = config["calibration"]
    calibration = calibrate(
        primitives,
        frame_spacing_mm=feet_inches_to_mm(cal_config["frame_spacing_ft"]),
        beam_mm=feet_inches_to_mm(cal_config["beam_ft"]),
        region=tuple(cal_config["region"]),
    )
    mm = calibration.mm_per_pt

    curves = [c for c in primitives.curves if _in_region(c.p0, region) and _in_region(c.p3, region)]
    segments = [s for s in primitives.segments if _in_region(s.midpoint, region) and s.length > 0.3]
    wall_segments = [s for s in segments if s.width >= 0.235]
    arcs = find_door_arcs(curves, 400 / mm, 1300 / mm)
    detected, unresolved = doors_from_arcs(arcs, segments, wall_segments)

    dots = detect_leader_dots(primitives.fills, region, segments=primitives.segments)
    leaders = find_leader_lines(primitives.segments, dots)
    wall_lines = build_wall_lines(segments, curves, detected, leaders, arcs)
    cells = free_cells(region, wall_lines)
    tree = STRtree(cells)

    placed_ocr = _ocr_labels(primitives, config, dots)
    report = _compare_labels(config, placed_ocr, cells, tree)
    entries = _reviewed_or_ocr(config, placed_ocr, llm)

    # One space per labelled cell. Two labels in one cell share it, such as a stair's two flights.
    spaces: list[Space] = []
    cell_to_space: dict[int, Space] = {}
    for entry in entries:
        cell = cell_near(cells, tree, entry["anchor"])
        if cell is None or cell.area < MIN_ROOM_AREA_PT2:
            continue
        existing = cell_to_space.get(id(cell))
        if existing is not None:
            if entry["compartment"] and entry["compartment"] not in (existing.compartment or ""):
                existing.compartment = f"{existing.compartment} / {entry['compartment']}"
            continue
        exterior, interiors = _polygon_mm(cell, mm)
        space = Space(
            id=entry["compartment"] or f"S-{len(spaces) + 1:02d}",
            name=entry["name"],
            compartment=entry["compartment"],
            category=entry["category"],
            classification_confidence=entry["confidence"],
            label_source=entry["source"],
            anchor_mm=(entry["anchor"][0] * mm, entry["anchor"][1] * mm),
            exterior_mm=exterior,
            interiors_mm=interiors,
            berths=entry["berths"],
            accessible=entry["accessible"],
        )
        spaces.append(space)
        cell_to_space[id(cell)] = space

    def space_for(cell: Polygon | None) -> str | None:
        if cell is None:
            return None
        existing = cell_to_space.get(id(cell))
        if existing is not None:
            return existing.id
        # A door leads here but no label does, such as a cabin's bathroom.
        exterior, interiors = _polygon_mm(cell, mm)
        center = cell.representative_point()
        space = Space(
            id=f"U-{sum(s.id.startswith('U-') for s in spaces) + 1:02d}",
            name="Unlabelled space",
            anchor_mm=(center.x * mm, center.y * mm),
            exterior_mm=exterior,
            interiors_mm=interiors,
        )
        spaces.append(space)
        cell_to_space[id(cell)] = space
        return space.id

    doors: list[Door] = []
    ordered = sorted(detected, key=lambda d: (round(d.hinge[0]), round(d.hinge[1])))
    for number, door in enumerate(ordered, start=1):
        side_a = space_for(_door_side_cell(cells, tree, door, 1.0))
        side_b = space_for(_door_side_cell(cells, tree, door, -1.0))
        # Positive normal in _door_side_cell is the side of the line with a positive area test.
        positive_side = side_of_line(door.hinge, door.latch, door.arc_mid) > 0
        doors.append(
            Door(
                id=f"D-{number:02d}",
                hinge_mm=(door.hinge[0] * mm, door.hinge[1] * mm),
                latch_mm=(door.latch[0] * mm, door.latch[1] * mm),
                leaf_tip_mm=(door.leaf_tip[0] * mm, door.leaf_tip[1] * mm),
                arc_mid_mm=(door.arc_mid[0] * mm, door.arc_mid[1] * mm),
                leaf_width_mm=door.radius_pt * mm,
                space_a=side_a,
                space_b=side_b,
                swings_into=side_a if positive_side else side_b,
                direction_confident=door.direction_confident,
            )
        )

    deck = Deck(
        name=config["name"],
        source_pdf=str(pdf_path.name),
        page_index=page_index,
        mm_per_pt=mm,
        relative_error=calibration.relative_error,
        extraction_tolerance_mm=calibration.extraction_tolerance_mm,
        calibration_note=(
            f"Frame ruler {calibration.frame_spacing_pt:.3f} pt per {calibration.frame_spacing_mm:.1f} mm frame; "
            f"beam measured {calibration.beam_measured_mm:.0f} mm against {calibration.beam_expected_mm:.0f} mm printed "
            f"({calibration.relative_error:.3%})."
        ),
        spaces=spaces,
        doors=doors,
        unresolved_arcs_mm=[(a.center[0] * mm, a.center[1] * mm) for a in unresolved],
        persons_other_decks=config.get("persons_other_decks", 0),
    )
    return deck, report
