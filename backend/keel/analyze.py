"""Whole-drawing analysis of any new plan: find spaces, name them, say what to check.

  Geometry (deterministic)  finds and numbers every separate space
  Vision model (AI reads)   names each numbered space
  OCR (independent reading) confirms the name is really printed on the drawing
  Fixed map (deterministic) lists what to check for that type of space
  Checks (deterministic)    measure what they can, only when a scale is given

Nothing here is reviewed, so AI names stay under the trust threshold. A result can be
PASS or NEEDS_REVIEW, never FAIL, until an engineer confirms the names.
"""
from __future__ import annotations

import logging
import re
import statistics
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

import cv2
import numpy as np
import yaml
from shapely.geometry import Point as ShapelyPoint, box
from shapely.strtree import STRtree

from keel.ai_look import look
from keel.checks import run_checks
from keel.geometry import inscribed_diameter
from keel.classify import LLM_CONFIDENCE_CAP, classify, classify_by_keyword
from keel.labels import (
    block_has_leader,
    group_blocks,
    trace_all_leaders,
    parse_compartment,
    place_labels,
    read_rotated_blocks,
    render_text_layer,
    run_ocr,
    run_ocr_tiled,
)
from keel.llm import LLM, LLMError
from keel.model import Category, Deck, Door, Space
from keel.raster import Segmentation, draw_numbers, load_gray
from keel.report import sort_findings
from keel.rules import load_rules
from keel.spaces import FoundSpaces, find_spaces
from keel.stairs import find_stairs
from keel.verdict import Finding, Verdict

log = logging.getLogger(__name__)

BACKEND = Path(__file__).resolve().parents[1]
UNCONFIRMED_NAME_CONFIDENCE = 0.4
SMALL_AREA_RATIO = 0.25  # Of the median named room. Smaller unnamed cells skip the AI.
LARGE_AREA_RATIO = 0.6  # Of the median room area. Bigger areas stay on the engineer's list.
DETAIL_AREA_RATIO = 0.1  # A far smaller area with the same compartment number is a room's detail.
# These depend on inputs a single unlabelled drawing does not give.
RULES_NEEDING_INPUT = {"ESC-STAIR-CAPACITY"}
UNIDENTIFIED = "Unidentified space"
STAIR_NUMBERS = 10000  # Detected stairs are numbered above any found space.
CLUTTER_LIMIT = 6.0  # Line work inside a stair box, as a multiple of its treads and rails.
GREY_LIMIT = 0.35  # Share of that line work drawn grey, as equipment detail is.
# Narrowest tread accepted as a stair. Rows of lockers drawn as bars were 545 to 550 mm on the
# research vessel GA; its narrowest real stair was 603 mm. A narrower stair still goes to review
# under its printed name, it is just not found from line work alone.
MIN_STAIR_MM = 580.0
# An arrowhead is 2.5 to 14 pt across on a sheet. On the research vessel GA every false stair
# (winches, lockers, a liferaft container) had none within 265 mm, and every real stair narrower
# than 700 mm had one.
ARROW_PT = (2.5, 14.0)
ARROW_MARGIN_MM = 265.0
KEEP_WITHOUT_ARROW_MM = 700.0
COULD_NOT_CHECK = ("No exit door", "0 independent", "Fewer than two doors", "This rule could not", "No door was found")
CORRIDOR_MAY_BE = {Category.UNKNOWN, Category.OPEN_DECK, Category.SERVICE, Category.PUBLIC}

NAMING_SCHEMA = {
    "type": "object",
    "properties": {
        "spaces": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "number": {"type": "integer"},
                    "name": {"type": "string"},
                    "compartment": {"type": "string"},
                    "category": {"type": "string", "enum": [c.value for c in Category]},
                    "is_room": {"type": "boolean"},
                    "confidence": {"type": "number"},
                    "evidence": {"type": "string", "enum": ["label_inside", "leader_line", "symbols_only", "none"]},
                },
                "required": ["number", "name", "category", "is_room", "confidence", "evidence"],
            },
        }
    },
    "required": ["spaces"],
}

NAMING_PROMPT = """This is part of a ship general arrangement drawing. Coloured areas with a white number on a red tag are separate floor areas found by geometry software.

For each number you can see, report what that area is:
- Use the room name printed on the drawing. A label may sit inside the area, or outside it with a thin leader line ending in a dot inside the area. Follow the line carefully.
- Copy the compartment number printed under the name, such as 1-33-0, or leave it empty.
- Set is_room to false for furniture (beds, desks, cabinets, lockers), equipment (winches, cranes, davits, fans, containers), hatches and hatch covers, deck fittings, tanks, voids and casings, and thin strips or slivers between lines. Only rooms, corridors, stairs and real areas of open deck are rooms.
- If no name is printed, give your best description from the symbols, set evidence to symbols_only and use low confidence. Do not invent a printed name.
- Do not measure anything and do not judge compliance.
- Confidence runs from 0 to 1 and states how sure you are that the name belongs to this area."""


@dataclass
class ChecklistItem:
    ref: str
    what: str
    confirmed_reference: bool
    status: str  # to_check | measured
    finding: Finding | None = None


@dataclass
class NamedSpace:
    number: int
    name: str
    compartment: str | None
    category: Category
    confidence: float
    evidence: str
    name_on_drawing: bool  # OCR independently found this name
    area_m2: float | None
    center_px: tuple[int, int]
    merged_from: list[int] = field(default_factory=list)
    checklist: list[ChecklistItem] = field(default_factory=list)


@dataclass
class SetAside:
    """An area left out of the room list. Always reported, so nothing vanishes silently."""

    number: int
    description: str
    reason: str


@dataclass
class Analysis:
    source: str
    page: int
    route: str
    scale_note: str
    llm_name: str | None
    naming_error: str | None
    spaces: list[NamedSpace]
    not_rooms: list[SetAside]
    annotated: np.ndarray
    region: tuple | None
    px_per_unit: float
    labels: np.ndarray
    plan: np.ndarray | None = None  # The clean drawing, with no tags or tint.
    plan_offset: tuple[int, int] = (0, 0)  # Where labels start on the plan.
    plan_origin: tuple[float, float] = (0.0, 0.0)  # Drawing units at the plan's top left corner.
    findings: list[Finding] = field(default_factory=list)
    mm_per_unit: float | None = None
    ship_type: str = "passenger"
    doors_found: int = 0
    stairs_found: int = 0


def _tiles(shape: tuple[int, int], max_side: int = 2600, overlap: float = 0.12) -> list[tuple[int, int, int, int]]:
    """Overlapping views, so that small print stays readable to the vision model."""
    height, width = shape
    columns = max(1, int(np.ceil(width / (max_side * (1 - overlap)))))
    rows = max(1, int(np.ceil(height / (max_side * (1 - overlap)))))
    tiles = []
    for row in range(rows):
        for column in range(columns):
            x0 = int(column * width / columns)
            y0 = int(row * height / rows)
            x1 = min(width, int((column + 1) * width / columns + overlap * width / columns))
            y1 = min(height, int((row + 1) * height / rows + overlap * height / rows))
            tiles.append((x0, y0, x1, y1))
    return tiles


def _context_view(found: FoundSpaces, path, page: int, margin_pt: float = 45.0, only: set[int] | None = None) -> tuple[np.ndarray, np.ndarray, int, int]:
    """The numbered plan and the clean plan, with a margin so outside labels stay visible."""
    if found.route == "vector" and found.region:
        x0, y0, x1, y1 = found.region
        scale = found.px_per_unit
        wider = (x0 - margin_pt, y0 - margin_pt, x1 + margin_pt, y1 + margin_pt)
        gray, _ = load_gray(path, page, int(round(scale * 72)), wider)
        ox, oy = int(margin_pt * scale), int(margin_pt * scale)
        labels = np.zeros(gray.shape, dtype=np.int32)
        h = min(found.segmentation.labels.shape[0], gray.shape[0] - oy)
        w = min(found.segmentation.labels.shape[1], gray.shape[1] - ox)
        labels[oy : oy + h, ox : ox + w] = found.segmentation.labels[:h, :w]
        shifted = []
        for space in found.segmentation.spaces:
            copy = type(space)(**{**space.__dict__, "center": (space.center[0] + ox, space.center[1] + oy)})
            shifted.append(copy)
        return draw_numbers(gray, Segmentation(labels, shifted, 0.0), only=only), gray, ox, oy
    return draw_numbers(found.gray, found.segmentation, only=only), found.gray, 0, 0


def name_with_vision(
    view: np.ndarray,
    spaces,
    offset: tuple[int, int],
    llm: LLM,
    on_view: Callable[[int, int], None] = lambda done, total: None,
) -> tuple[dict[int, dict], int, int]:
    """Ask the vision model about each tile. Returns (answers, views failed, views total)."""
    jobs = []
    for x0, y0, x1, y1 in _tiles(view.shape[:2]):
        present = [
            s.number
            for s in spaces
            if x0 <= s.center[0] + offset[0] < x1 and y0 <= s.center[1] + offset[1] < y1
        ]
        ok, encoded = cv2.imencode(".jpg", view[y0:y1, x0:x1], [cv2.IMWRITE_JPEG_QUALITY, 88])
        if present and ok:
            jobs.append((present, encoded.tobytes()))

    def ask(job):
        present, image = job
        prompt = f"{NAMING_PROMPT}\n\nNumbers expected in this view: {present}"
        return present, llm.complete_json(prompt, NAMING_SCHEMA, images=[image])

    answers: dict[int, dict] = {}
    failures = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(ask, job) for job in jobs]
        on_view(0, len(jobs))
        for done, future in enumerate(futures, start=1):
            try:
                present, result = future.result()
            except LLMError as error:
                failures += 1
                log.warning("A view could not be named: %s", error)
                continue
            finally:
                on_view(done, len(jobs))
            for item in result.get("spaces", []):
                number = item.get("number")
                if number in present and float(item.get("confidence", 0)) >= float(answers.get(number, {}).get("confidence", -1)):
                    answers[number] = item
    return answers, failures, len(jobs)


def _compact(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def name_is_printed(name: str, printed: list[str], threshold: float = 0.8) -> bool:
    """True if OCR, reading independently, also found this name on the drawing."""
    wanted = _compact(name)
    if len(wanted) < 2:
        return False
    return any(
        wanted in text or SequenceMatcher(None, wanted, text).ratio() >= threshold
        for text in (_compact(p) for p in printed)
    )


def _ocr_printed_text(gray: np.ndarray) -> list[str]:
    """OCR in tiles, because small print is lost on a very large image."""
    texts: list[str] = []
    for x0, y0, x1, y1 in _tiles(gray.shape, max_side=1800):
        crop = cv2.cvtColor(gray[y0:y1, x0:x1], cv2.COLOR_GRAY2RGB)
        from PIL import Image

        items = run_ocr(Image.fromarray(crop), (0, 0, 0, 0), 1.0)
        texts.extend(block.name for block in group_blocks(items) if block.name)
        texts.extend(item.text for item in items)
    return texts


OCR_SCALE = 6.0
PLAN_TITLE = re.compile(r"^\s*(PLAN|ELEVATION|SECTION)\s+[\dA-Z]+-", re.IGNORECASE)
# Stair arrows and short drawing marks are printed text, but they do not name a room.
DRAWING_MARK = re.compile(r"^\W*(UP|DN|DOWN|[A-Z]?\d*|[A-Z]\d?)\W*$", re.IGNORECASE)


def _is_room_text(block) -> bool:
    return bool(block.name) and not PLAN_TITLE.match(block.name) and not DRAWING_MARK.match(block.name)


def read_printed_labels(found: FoundSpaces, margin_pt: float = 45.0) -> dict[int, dict]:
    """Vector drawings only: name spaces from geometry and OCR, with no vision model.

    A leader line is real geometry, so it can be followed exactly from the dot in the room to
    the printed text. A vision model cannot follow hair-thin lines reliably.
    Text with no leader names the room it is printed in.
    """
    if found.route != "vector" or found.primitives is None:
        return {}
    # Read around the spaces actually found, not the title block and empty sheet.
    bounds = [cell.bounds for cell in found.cells_pt.values()]
    x0, y0 = min(b[0] for b in bounds), min(b[1] for b in bounds)
    x1, y1 = max(b[2] for b in bounds), max(b[3] for b in bounds)
    wide = (x0 - margin_pt, y0 - margin_pt, x1 + margin_pt, y1 + margin_pt)
    inside = lambda p: wide[0] <= p[0] <= wide[2] and wide[1] <= p[1] <= wide[3]
    segments = [s for s in found.primitives.segments if inside(s.midpoint)]
    curves = [c for c in found.primitives.curves if inside(c.p0)]
    traces, tails = trace_all_leaders(found.dots, segments)
    image = render_text_layer(segments, curves, wide, scale=OCR_SCALE, exclude=tails)
    blocks = [b for b in group_blocks(run_ocr_tiled(image, wide, OCR_SCALE)) if _is_room_text(b)]
    blocks += read_rotated_blocks(image, wide, OCR_SCALE)
    placed = place_labels(blocks, found.dots, segments, traces=traces)

    cells = list(found.cells_pt.values())
    numbers = list(found.cells_pt.keys())
    tree = STRtree(cells)

    def containing(point) -> int | None:
        shape = ShapelyPoint(point)
        hits = [numbers[int(i)] for i in tree.query(shape) if cells[int(i)].contains(shape)]
        return hits[0] if hits else None

    names: dict[int, dict] = {}
    for label in placed:
        if label.via == "leader" and label.block.name:
            number = containing(label.anchor) or _largest_near(cells, numbers, tree, label.anchor, 3.0)
            if number is not None:
                names.setdefault(number, _printed_entry(label.block, "leader_line"))
    in_room: dict[int, list] = {}
    for label in placed:
        block = label.block
        if label.via != "in_room" or not block.name or block_has_leader(block, segments, tails):
            continue
        number = _largest_touching(cells, numbers, tree, block)
        # A numbered label printed in the room beats a leader note like "CTD STOWED POSITION".
        weak_leader = number in names and not names[number]["compartment"]
        if number is not None and (number not in names or (weak_leader and block.compartment)):
            in_room.setdefault(number, []).append(block)
    for number, blocks_here in in_room.items():
        # A real room label carries a compartment number; stray marks and notes do not.
        numbered = [b for b in blocks_here if b.compartment]
        if len(numbered) == 1:
            names[number] = _printed_entry(numbered[0], "label_inside")
        elif len(blocks_here) == 1:
            names[number] = _printed_entry(blocks_here[0], "label_inside")
        # Otherwise it is ambiguous, so the space stays open for the vision model or review.
    return names


def read_printed_labels_raster(found: FoundSpaces, gray: np.ndarray) -> dict[int, dict]:
    """Images have no leader geometry, so only text printed inside a space can be used here."""
    from PIL import Image

    height, width = gray.shape
    image = Image.fromarray(gray)
    blocks = [
        b for b in group_blocks(run_ocr_tiled(image, (0.0, 0.0, 0.0, 0.0), 1.0)) if _is_room_text(b)
    ]
    labels = found.segmentation.labels
    found_labels: dict[int, list] = {}
    for block in blocks:
        x0, y0 = max(0, int(block.x0)), max(0, int(block.y0))
        x1, y1 = min(width, int(block.x1) + 1), min(height, int(block.y1) + 1)
        values, counts = np.unique(labels[y0:y1, x0:x1], return_counts=True)
        nonzero = [(c, v) for v, c in zip(values, counts) if v != 0]
        if nonzero:
            found_labels.setdefault(int(max(nonzero)[1]), []).append(block)
    names: dict[int, dict] = {}
    for number, here in found_labels.items():
        numbered = [b for b in here if b.compartment]
        chosen = numbered[0] if len(numbered) == 1 else (here[0] if len(here) == 1 else None)
        if chosen is not None:
            names[number] = _printed_entry(chosen, "label_inside")
    return names


def _printed_entry(block, evidence: str) -> dict:
    return {
        "name": re.sub(r"\s*[-—]\s*$", "", block.name.strip()),
        "compartment": block.compartment or "",
        "confidence": block.confidence,
        "evidence": evidence,
        "is_room": True,
        "printed": True,
    }


def _largest_near(cells, numbers, tree, point, radius: float) -> int | None:
    disk = ShapelyPoint(point).buffer(radius)
    hits = [int(i) for i in tree.query(disk) if cells[int(i)].intersects(disk)]
    return numbers[max(hits, key=lambda i: cells[i].area)] if hits else None


def _largest_touching(cells, numbers, tree, block, grow: float = 6.0) -> int | None:
    """Text is often printed over equipment in a room. The room is the largest area it touches."""
    from shapely.geometry import box as shapely_box

    area = shapely_box(block.x0 - grow, block.y0 - grow, block.x1 + grow, block.y1 + grow)
    hits = [int(i) for i in tree.query(area) if cells[int(i)].intersects(area)]
    return numbers[max(hits, key=lambda i: cells[i].area)] if hits else None


def load_applicability(path: str | Path | None = None) -> dict:
    return yaml.safe_load(Path(path or BACKEND / "config/applicability.yaml").read_text())


def checklist_for(category: Category, table: dict, findings: list[Finding], subject_id: str, door_ids: set[str]) -> list[ChecklistItem]:
    items = []
    for entry in table.get(category.value, table["unknown"]):
        rule = entry.get("rule")
        match = next(
            (f for f in findings if rule and f.rule_id == rule and (f.subject_id == subject_id or f.subject_id in door_ids)),
            None,
        )
        items.append(
            ChecklistItem(entry["ref"], entry["what"], bool(entry.get("confirmed")), "measured" if match else "to_check", match)
        )
    return items


def _merge_same_names(named: list[NamedSpace], labels: np.ndarray) -> list[NamedSpace]:
    """Geometry over-splits. Neighbours with the same printed name and number are one room."""
    kernel = np.ones((7, 7), np.uint8)
    keep: list[NamedSpace] = []
    for space in named:
        merged = False
        if space.evidence in ("label_inside", "leader_line") and space.name_on_drawing:
            mask = cv2.dilate((labels == space.number).astype(np.uint8), kernel)
            for other in keep:
                if (
                    _compact(other.name) == _compact(space.name)
                    and (other.compartment or "") == (space.compartment or "")
                    and (mask & (labels == other.number).astype(np.uint8)).any()
                ):
                    labels[labels == space.number] = other.number
                    other.merged_from.append(space.number)
                    if other.area_m2 is not None and space.area_m2 is not None:
                        other.area_m2 += space.area_m2
                    merged = True
                    break
        if not merged:
            keep.append(space)
    return keep


def _set_aside_details(named: list[NamedSpace], labels: np.ndarray) -> tuple[list[NamedSpace], list[SetAside]]:
    """A bench or bed cell often gets its room's label. A compartment number is unique, so a
    far smaller area carrying the same number is a detail of that room, not a second room."""
    largest: dict[str, int] = {}
    for space in named:
        if space.compartment:
            largest[space.compartment] = max(largest.get(space.compartment, 0), int((labels == space.number).sum()))
    keep, details = [], []
    for space in named:
        size = int((labels == space.number).sum())
        if space.compartment and size < DETAIL_AREA_RATIO * largest[space.compartment]:
            details.append(SetAside(space.number, space.name, f"Detail inside {space.name} {space.compartment}"))
        else:
            keep.append(space)
    return keep, details


def _door_side(cells, tree, numbers, door, sign: float) -> int | None:
    mid = ((door.hinge[0] + door.latch[0]) / 2, (door.hinge[1] + door.latch[1]) / 2)
    dx, dy = door.latch[0] - door.hinge[0], door.latch[1] - door.hinge[1]
    length = (dx * dx + dy * dy) ** 0.5
    nx, ny = -dy / length * sign, dx / length * sign
    for along in (0.0, 0.25, -0.25):
        start = (mid[0] + dx * along, mid[1] + dy * along)
        for offset in (1.0, 2.0, 3.0, 4.5, 6.0, 8.0):
            point = ShapelyPoint(start[0] + nx * offset, start[1] + ny * offset)
            for index in tree.query(point):
                if cells[int(index)].contains(point):
                    return numbers[int(index)]
    return None


JUNK_NAME = re.compile(
    r"^(\W*|[\d.,\s]+|for|tray|shel[fe]|table|chairs?|sofa.*|.*\b(table|sofa|seating|chairs?)\b.*)$", re.IGNORECASE
)
CREW_CABIN_MARK = re.compile(r"^\d\s*M$", re.IGNORECASE)  # "2M": a cabin for two.


# Things a GA plan draws and labels that are not rooms anyone works in or escapes from.
EQUIPMENT = re.compile(
    r"HATCH|HAICH|CABLE[\s-]*(DUCT|TRAY|IRAY)|CRANE|DAVIT|BOOM|GALLOW|FITTING|\bBERTH|\bBEDS?\b|DESK|"
    r"CABINET|FURNITURE|COUNTER|\bFAN\b|CONTAINER|STRIP|EDGE|THRESHOLD|STRUCTURE",
    re.IGNORECASE,
)
# FO, DO, LO, FW and BW are the usual GA marks for fuel, diesel, lube oil, fresh and ballast water tanks.
TANK_OR_VOID = re.compile(r"TANK|TK\b|VOID|CASING|UPTAKE|^(FO|DO|LO|FW|BW)$", re.IGNORECASE)
SHORT_ROOM_NAMES = re.compile(r"^(WC|NH3|CO2|ECR|AC ROOM)$", re.IGNORECASE)
GUESSED = {"symbols_only", "none"}
SLIVER_M2 = 1.0  # An AI guess smaller than this is a gap between lines, not a room.
SMALL_UNNAMED_M2 = 2.0
SMALL_OPEN_DECK_M2 = 5.0  # Open deck is cut into pieces by every line; small pieces are noise.
EQUIPMENT_KEEP_M2 = 6.0  # "CTD WINCH" printed on 104 m2 of open deck still names that deck.


def _readable(name: str) -> bool:
    """A real label has at least four plain letters. OCR noise such as "④", "5Φ" or "7d" does not."""
    name = name.strip()
    return bool(CREW_CABIN_MARK.match(name) or SHORT_ROOM_NAMES.match(name)) or len(re.findall(r"[A-Za-z]", name)) >= 4


def _non_room_reason(space: NamedSpace) -> str | None:
    """Why this area is not a room, or None to keep it."""
    name = space.name.strip()
    area = space.area_m2
    guessed = space.evidence in GUESSED and not space.name_on_drawing
    if space.category == Category.STAIR or space.evidence == "treads":
        return None
    if TANK_OR_VOID.search(name):
        return "Tank, void or casing, not a room"
    if EQUIPMENT.search(name) and (area is None or area < EQUIPMENT_KEEP_M2):
        return "Equipment, furniture, a fitting or a thin strip, not a room"
    if name not in (UNIDENTIFIED, "Unnamed space") and not _readable(name):
        return "Unreadable label, not a room name"
    if area is None:
        return None
    if guessed and area < SLIVER_M2:
        return "Small gap between lines, read by AI from symbols only"
    if name in (UNIDENTIFIED, "Unnamed space") and area < SMALL_UNNAMED_M2:
        return "Small unnamed area"
    if guessed and space.category == Category.OPEN_DECK and area < SMALL_OPEN_DECK_M2:
        return "Small piece of open deck"
    return None


def _set_aside_non_rooms(named: list[NamedSpace]) -> tuple[list[NamedSpace], list[SetAside]]:
    kept, aside = [], []
    for space in named:
        if CREW_CABIN_MARK.match(space.name.strip()):
            space.category = Category.CABIN  # "1M", "2M": crew cabins, on every deck.
        reason = _non_room_reason(space)
        if reason:
            aside.append(SetAside(space.number, space.name, reason))
        else:
            kept.append(space)
    return kept, aside


def _clean_exploded_names(named: list[NamedSpace]) -> None:
    """On a dense plan, OCR and AI also read furniture and stray marks. Those are not room names."""
    for space in named:
        if CREW_CABIN_MARK.match(space.name.strip()):
            space.category = Category.CABIN
        elif JUNK_NAME.match(space.name.strip()):
            space.name, space.category, space.confidence = "Unidentified space", Category.UNKNOWN, 0.0
            space.name_on_drawing = False


def _mark_corridors(found: FoundSpaces, named: list[NamedSpace], mm_per_pt: float) -> None:
    """Corridors often have no printed name. Long, narrow and lined with doors is a corridor.

    This is read from shape, so its confidence stays below the trust level: a shortfall can
    only go to an engineer, never to FAIL.
    """
    named_passage = re.compile(r"passage|corridor|walkway", re.IGNORECASE)
    for space in named:
        cell = found.cells_pt.get(space.number)
        if cell is None:
            continue
        width, _ = inscribed_diameter(cell)
        if width <= 0:
            continue
        width_mm = width * mm_per_pt
        if space.category == Category.STAIR and width_mm < 500:
            # Read as a stair from its name, but too thin to walk: a sliver beside one.
            space.category, space.confidence = Category.UNKNOWN, 0.0
            continue
        if space.category != Category.CORRIDOR and space.category not in CORRIDOR_MAY_BE:
            continue
        if space.category == Category.CORRIDOR and width_mm < 500:
            space.category, space.confidence = Category.UNKNOWN, 0.0
            continue
        doors = sum(cell.distance(ShapelyPoint(d.hinge)) <= 3.0 for d in found.doors)
        long_and_narrow = 500 <= width_mm <= 3000 and cell.area / (width * width) >= 3.5
        passage_by_name = space.category == Category.CORRIDOR or bool(named_passage.search(space.name))
        if long_and_narrow and (doors >= 3 or passage_by_name):
            space.category = Category.CORRIDOR
            space.confidence = min(space.confidence or 0.7, 0.7)
            space.evidence = "shape"
            if not space.name_on_drawing:
                space.name = "Corridor"
        elif space.category == Category.CORRIDOR:
            space.evidence = "shape"


def _cluttered(stair, segments) -> bool:
    """A stair plan holds treads, two side rails and an arrow. A winch drawn with parallel bars
    has far more line work inside the same box, much of it grey detail, so it is not a stair.

    On the 60 m research vessel GA, real stairs had 1.1 to 4.5 times the line work of their
    treads and rails, and none were mostly grey. Two trawl winches had 10.4 times, 38% grey.
    """
    bx0, by0, bx1, by1 = stair.box
    inside = [s for s in segments if bx0 <= s.midpoint[0] <= bx1 and by0 <= s.midpoint[1] <= by1]
    ink = sum(s.length for s in inside)
    grey = sum(s.length for s in inside if s.gray)
    expected = stair.treads * stair.width + 2 * max(bx1 - bx0, by1 - by0)
    return ink > CLUTTER_LIMIT * expected or (ink > 0 and grey / ink > GREY_LIMIT)


def arrowheads(path: str | Path, page: int) -> list[tuple[float, float]]:
    """Centres of small filled shapes, such as the arrowhead showing which way a stair goes up."""
    import pymupdf

    with pymupdf.open(path) as document:
        return [
            ((d["rect"].x0 + d["rect"].x1) / 2, (d["rect"].y0 + d["rect"].y1) / 2)
            for d in document[page].get_drawings()
            if d["type"] in ("f", "fs") and ARROW_PT[0] <= max(d["rect"].width, d["rect"].height) <= ARROW_PT[1]
        ]


def _looks_like_stair(stair, heads: list[tuple[float, float]], mm_per_pt: float) -> bool:
    """Every stair on a plan has an arrow showing the way up. Lockers, winches and liferaft
    containers drawn with bars have none. Some stairs have their arrow just past the treads, so
    the box is searched with a margin, and a stair of the usual escape width is kept anyway."""
    if stair.width * mm_per_pt >= KEEP_WITHOUT_ARROW_MM:
        return True
    margin = ARROW_MARGIN_MM / mm_per_pt
    bx0, by0, bx1, by1 = stair.box
    return any(bx0 - margin <= x <= bx1 + margin and by0 - margin <= y <= by1 + margin for x, y in heads)


def _detected_stairs(found: FoundSpaces, named: list[NamedSpace], mm_per_pt: float, labels: np.ndarray, table: dict, heads: list[tuple[float, float]] | None = None) -> list[NamedSpace]:
    """Stairs drawn inside bigger spaces have no room of their own, so add them as spaces.

    They are read from their treads, not a label, so the confidence stays below the trust level
    and an engineer confirms each. A false stair can then only ever reach review.
    """
    x0, y0, x1, y1 = found.region
    inside = [
        s for s in found.primitives.segments
        if x0 <= s.midpoint[0] <= x1 and y0 <= s.midpoint[1] <= y1 and s.width > 0
    ]
    every_line = [s for s in found.primitives.segments if x0 <= s.midpoint[0] <= x1 and y0 <= s.midpoint[1] <= y1]
    stairs = [
        s for s in find_stairs(inside, (MIN_STAIR_MM / mm_per_pt, 2000 / mm_per_pt), (150 / mm_per_pt, 400 / mm_per_pt))
        if not _cluttered(s, every_line) and (heads is None or _looks_like_stair(s, heads, mm_per_pt))
    ]
    boxes = [box(*s.box) for s in stairs]
    known = []
    for space in named:
        cell = found.cells_pt.get(space.number)
        if space.category != Category.STAIR or cell is None:
            continue
        has_treads = any(cell.intersection(b).area > 0.5 * b.area for b in boxes)
        if not space.name_on_drawing and not has_treads:
            # The AI guessed "stair" from symbols, but no treads are drawn here: say so plainly.
            space.name, space.category, space.confidence, space.evidence = "Unnamed space", Category.UNKNOWN, 0.0, "none"
            continue
        known.append(cell)
    extra: list[NamedSpace] = []
    for index, stair in enumerate(stairs, start=1):
        bx0, by0, bx1, by1 = stair.box
        center = ((bx0 + bx1) / 2, (by0 + by1) / 2)
        outline = boxes[index - 1]
        if any(cell.contains(ShapelyPoint(center)) or cell.intersection(outline).area > 0.5 * outline.area for cell in known):
            continue
        number = STAIR_NUMBERS + index
        scale = found.px_per_unit
        labels[int((by0 - y0) * scale) : int((by1 - y0) * scale) + 1, int((bx0 - x0) * scale) : int((bx1 - x0) * scale) + 1] = number
        space = NamedSpace(
            number, f"Stairway {len(extra) + 1}", None, Category.STAIR, 0.7, "treads", False,
            (bx1 - bx0) * (by1 - by0) * (mm_per_pt / 1000) ** 2, (int((center[0] - x0) * scale), int((center[1] - y0) * scale)),
        )
        extra.append(space)
        found.cells_pt[number] = box(bx0, by0, bx1, by1)
    return extra


def _to_deck(found: FoundSpaces, named: list[NamedSpace], mm_per_pt: float, source: str, page: int, merged_into: dict[int, int], relative_error: float = 0.005) -> Deck:
    """Build the same ship model the reviewed pipeline uses, so all checks run unchanged."""
    from keel.geometry import side_of_line

    by_number = {s.number: s for s in named}
    spaces = []
    for number, cell in found.cells_pt.items():
        owner = merged_into.get(number, number)
        info = by_number.get(owner)
        if info is None or owner != number:
            continue
        spaces.append(
            Space(
                id=f"N{number:02d}",
                name=info.name,
                compartment=info.compartment,
                category=info.category,
                classification_confidence=info.confidence,
                label_source="shape" if info.evidence == "shape" else "ai_vision",
                anchor_mm=(cell.representative_point().x * mm_per_pt, cell.representative_point().y * mm_per_pt),
                exterior_mm=[(x * mm_per_pt, y * mm_per_pt) for x, y in cell.exterior.coords],
                interiors_mm=[[(x * mm_per_pt, y * mm_per_pt) for x, y in ring.coords] for ring in cell.interiors],
            )
        )
    cells = list(found.cells_pt.values())
    numbers = list(found.cells_pt.keys())
    tree = STRtree(cells)
    known = {s.id for s in spaces}

    def space_id(number: int | None) -> str | None:
        if number is None:
            return None
        identifier = f"N{merged_into.get(number, number):02d}"
        return identifier if identifier in known else None

    doors = []
    for index, door in enumerate(sorted(found.doors, key=lambda d: (round(d.hinge[0]), round(d.hinge[1]))), start=1):
        a = space_id(_door_side(cells, tree, numbers, door, 1.0))
        b = space_id(_door_side(cells, tree, numbers, door, -1.0))
        # On a very detailed drawing, cabinet doors also have arcs. A real door joins two spaces.
        if found.exploded and (a is None or a == b):
            continue
        positive = side_of_line(door.hinge, door.latch, door.arc_mid) > 0
        doors.append(
            Door(
                id=f"D-{index:02d}",
                hinge_mm=(door.hinge[0] * mm_per_pt, door.hinge[1] * mm_per_pt),
                latch_mm=(door.latch[0] * mm_per_pt, door.latch[1] * mm_per_pt),
                leaf_tip_mm=(door.leaf_tip[0] * mm_per_pt, door.leaf_tip[1] * mm_per_pt),
                arc_mid_mm=(door.arc_mid[0] * mm_per_pt, door.arc_mid[1] * mm_per_pt),
                leaf_width_mm=door.radius_pt * mm_per_pt,
                space_a=a,
                space_b=b,
                swings_into=a if positive else b,
                direction_confident=door.direction_confident,
            )
        )
    return Deck(
        name=f"{Path(source).name} page {page}",
        source_pdf=Path(source).name,
        page_index=page,
        mm_per_pt=mm_per_pt,
        relative_error=relative_error,
        extraction_tolerance_mm=0.36 * mm_per_pt,
        spaces=spaces,
        doors=doors,
    )


def analyze(
    path: str | Path,
    llm: LLM | None,
    page: int = 0,
    region: tuple | None = None,
    mm_per_unit: float | None = None,
    on_step: Callable[[str, str], None] = lambda step, detail: None,
    ship_type: str = "passenger",
    relative_error: float = 0.005,
    scale_note_override: str | None = None,
) -> Analysis:
    """Analyse a new drawing. mm_per_unit is mm per PDF point, or per pixel for an image.

    on_step(step, detail) reports progress, so a caller can show what is happening.
    """
    path = Path(path)
    on_step("Finding rooms and doors", "")
    found = find_spaces(path, page, region, mm_per_unit if path.suffix.lower() == ".pdf" else None)
    clean, ox, oy = _context_view(found, path, page, only=set())[1:]

    # First what geometry and OCR can prove, then the vision model for whatever is left.
    on_step("Reading room labels", "")
    answers: dict[int, dict] = read_printed_labels(found) if found.route == "vector" else read_printed_labels_raster(found, found.gray)
    # The vector reader relies on the text line weight of one CAD standard. If it finds nothing,
    # read the rendered plan instead, which works for any drawing.
    if found.route == "vector" and not answers:
        answers = read_printed_labels_raster(found, found.gray)
    # Tiny unnamed cells are nearly always furniture, so they are not worth AI calls.
    named_sizes = [s.area_px for s in found.segmentation.spaces if s.number in answers]
    typical = statistics.median(named_sizes) if named_sizes else 0
    remaining = [
        s for s in found.segmentation.spaces if s.number not in answers and s.area_px >= SMALL_AREA_RATIO * typical
    ]
    naming_error = None
    if llm is None:
        if remaining:
            naming_error = f"No LLM was used, so {len(remaining)} unlabelled spaces could not be identified."
    elif remaining:
        untagged = {s.number for s in remaining}
        tagged = _context_view(found, path, page, only=untagged)[0]
        step = f"Asking AI to name {len(remaining)} rooms"
        on_step(step, "")
        found_answers, failed, total = name_with_vision(
            tagged, remaining, (ox, oy), llm, lambda done, views: on_step(step, f"{done} of {views} views")
        )
        answers.update(found_answers)
        if failed:
            naming_error = f"The vision model failed on {failed} of {total} views, so some spaces stay unidentified."

    on_step("Reading printed text", "")
    printed = _ocr_printed_text(clean)

    on_step("Building the checklist", "")
    area_factor = None
    if mm_per_unit:
        unit_per_px = 1.0 / found.px_per_unit
        area_factor = (unit_per_px * mm_per_unit / 1000.0) ** 2

    named: list[NamedSpace] = []
    not_rooms: list[SetAside] = []
    labels = found.segmentation.labels.copy()
    # Printed names the keyword table does not know still need a type, such as "2ND MATE".
    unknown_printed = sorted(
        {a["name"] for a in answers.values() if a.get("printed") and not classify_by_keyword(a["name"])}
    )
    text_categories = classify(unknown_printed, llm) if unknown_printed else {}
    room_areas = [s.area_px for s in found.segmentation.spaces if answers.get(s.number, {}).get("is_room")]
    typical_area = statistics.median(room_areas) if room_areas else 0
    for space in found.segmentation.spaces:
        answer = answers.get(space.number)
        if answer is None and space.area_px < SMALL_AREA_RATIO * typical:
            not_rooms.append(SetAside(space.number, "Small unlabelled area", "Too small to be a room, with no label"))
            continue
        if answer is not None and not answer.get("is_room", True):
            # The AI may set aside a small area, but cannot remove one as large as a real room.
            if space.area_px < LARGE_AREA_RATIO * typical_area:
                not_rooms.append(SetAside(space.number, answer.get("name", ""), "AI read it as furniture or equipment"))
                continue
            answer = {**answer, "evidence": "none", "confidence": min(float(answer.get("confidence", 0)), 0.3)}
        name = (answer or {}).get("name", "").strip() or "Unidentified space"
        evidence = (answer or {}).get("evidence", "none")
        on_drawing = bool(answer) and (
            bool(answer.get("printed"))
            or (evidence in ("label_inside", "leader_line") and name_is_printed(name, printed))
        )
        keyword = classify_by_keyword(name)
        try:
            ai_category = Category((answer or {}).get("category", "unknown"))
        except ValueError:
            ai_category = Category.UNKNOWN
        category = keyword[0] if keyword else text_categories.get(name, (ai_category, 0.0))[0]
        # An AI name is never trusted alone, and less so if OCR did not see it printed.
        raw = float((answer or {}).get("confidence", 0.0))
        confidence = min(raw, LLM_CONFIDENCE_CAP if on_drawing else UNCONFIRMED_NAME_CONFIDENCE)
        compartment = parse_compartment((answer or {}).get("compartment") or "") or None
        named.append(
            NamedSpace(
                space.number, name, compartment, category, confidence, evidence, on_drawing,
                space.area_px * area_factor if area_factor else None, space.center,
            )
        )

    named = _merge_same_names(named, labels)
    named, details = _set_aside_details(named, labels)
    not_rooms.extend(details)
    named, not_spaces = _set_aside_non_rooms(named)
    not_rooms.extend(not_spaces)
    merged_into = {old: s.number for s in named for old in s.merged_from}
    table = load_applicability()

    findings: list[Finding] = []
    deck = None
    if mm_per_unit and found.route == "vector":
        if found.exploded:
            _clean_exploded_names(named)
            _mark_corridors(found, named, mm_per_unit)
        # An AI guess from symbols alone, such as "deck passage", is not enough to check a space
        # as a corridor. A printed name or the corridor shape is.
        for space in named:
            if space.category == Category.CORRIDOR and not space.name_on_drawing and space.evidence != "shape":
                space.category = Category.UNKNOWN
        # On every deck: an AI "stair" with no drawn treads is not called a stair.
        named = named + _detected_stairs(found, named, mm_per_unit, labels, table, arrowheads(path, page))
        deck = _to_deck(found, named, mm_per_unit, str(path), page, merged_into, relative_error)
        rules = [r for r in load_rules(BACKEND / "rules", "escape", ship_type) if r.id not in RULES_NEEDING_INPUT]
        findings = run_checks(deck, rules)
        if llm is not None:
            # Where the code could not measure, the AI looks and reports what it sees.
            check_of = {r.id: r.check for r in rules}
            # Also the engine room when fewer than two ways out were found: a ladder or escape
            # trunk the code cannot see is exactly what the AI can look for.
            blind = [
                f for f in findings
                if _could_not_check(f)
                or (check_of.get(f.rule_id) == "machinery_a_escape" and f.verdict == Verdict.NEEDS_REVIEW)
            ]
            if blind:
                step = f"AI looking at {len(blind)} checks Keel could not measure"
                on_step(step, "")
                look(
                    path, page, blind, check_of, llm, found.region,
                    lambda done, total: on_step(step, f"{done} of {total}"),
                )

    for space in named:
        subject = f"N{space.number:02d}"
        door_ids = {d.id for d in deck.doors_of(subject)} if deck else set()
        space.checklist = checklist_for(space.category, table, findings, subject, door_ids)

    scale_note = scale_note_override or (
        f"Scale given: {mm_per_unit} mm per unit, not verified against a second dimension."
        if mm_per_unit
        else "No scale given, so nothing was measured. Provide a scale to measure."
    )
    # Tag only the spaces listed for the engineer. Set-aside areas can run to hundreds of tags,
    # which would bury the plan.
    annotated = _context_view(found, path, page, only={s.number for s in named})[0]
    return Analysis(
        str(path), page, found.route, scale_note, llm.name if llm else None, naming_error,
        named, not_rooms, annotated, found.region, found.px_per_unit, labels, clean, (ox, oy),
        ((found.region[0] - ox / found.px_per_unit), (found.region[1] - oy / found.px_per_unit)) if found.route == "vector" and found.region else (0.0, 0.0),
        findings, mm_per_unit, ship_type, len(deck.doors) if deck else 0,
        sum(1 for s in named if s.number > STAIR_NUMBERS),
    )


def _outline_px(labels: np.ndarray, number: int, offset: tuple[int, int]) -> list[list[list[int]]]:
    """A space's outlines on the plan image, simplified so the result stays small."""
    contours, _ = cv2.findContours((labels == number).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    outlines = []
    for contour in contours:
        points = cv2.approxPolyDP(contour, 1.5, True).reshape(-1, 2)
        if len(points) >= 3:
            outlines.append([[int(x) + offset[0], int(y) + offset[1]] for x, y in points])
    return outlines


def _checklist_json(checklist: list[ChecklistItem]) -> list[dict]:
    return [
        {
            "ref": item.ref,
            "what": item.what,
            "reference_confirmed": item.confirmed_reference,
            "status": item.status,
            "verdict": item.finding.verdict.value if item.finding else None,
            "measured": item.finding.why if item.finding else None,
        }
        for item in checklist
    ]


def space_types() -> list[str]:
    """The types of space that have a regulation list."""
    return sorted(load_applicability())


def rename_space(space: dict, name: str, category: str | None) -> dict:
    """An engineer's correction of a saved space. Type comes from the engineer, else the name.

    The regulations are the fixed list for the type. If the type changes, the old list's
    measurements no longer apply, so everything returns to be checked.
    """
    table = load_applicability()
    keyword = classify_by_keyword(name)
    new_category = category or (keyword[0].value if keyword else space["category"])
    if new_category not in table:
        raise ValueError(f"unknown type of space: {new_category}")
    changed = new_category != space["category"]
    return {
        **space,
        "name": name,
        "category": new_category,
        "confidence": 1.0,
        "evidence": "engineer",
        "reviewed": True,
        "checklist": _checklist_json(checklist_for(Category(new_category), table, [], "", set()))
        if changed
        else space["checklist"],
    }


def _could_not_check(finding: Finding) -> bool:
    """Keel lacked what it needed, such as doors. That is a gap to report, not a finding."""
    if finding.verdict != Verdict.NEEDS_REVIEW or finding.measured_mm is not None or finding.ai_look:
        return False
    return finding.subject_id == "deck" or finding.why.startswith(COULD_NOT_CHECK)


def analysis_json(result: Analysis) -> dict:
    """The full result for the API. Geometry evidence stays with each measured finding."""
    ranked = sort_findings(result.findings)
    return {
        "plan_size": [int(result.plan.shape[1]), int(result.plan.shape[0])],
        "plan_scale": result.px_per_unit,
        "plan_origin": list(result.plan_origin),
        "mm_per_unit": result.mm_per_unit,
        "ship_type": result.ship_type,
        "doors_found": result.doors_found,
        "stairs_found": result.stairs_found,
        "findings": [
            {**f.model_dump(mode="json"), "pin": f"F-{i:02d}", "could_not_check": _could_not_check(f)}
            for i, f in enumerate(ranked, start=1)
        ],
        "source": Path(result.source).name,
        "page": result.page,
        "route": result.route,
        "scale_note": result.scale_note,
        "llm": result.llm_name,
        "naming_error": result.naming_error,
        "reviewed": False,
        "spaces": [
            {
                "number": s.number,
                "name": s.name,
                "compartment": s.compartment,
                "category": s.category.value,
                "confidence": round(s.confidence, 2),
                "evidence": s.evidence,
                "name_on_drawing": s.name_on_drawing,
                "area_m2": round(s.area_m2, 1) if s.area_m2 is not None else None,
                "merged_from": s.merged_from,
                "reviewed": False,
                "outline_px": _outline_px(result.labels, s.number, result.plan_offset),
                "checklist": _checklist_json(s.checklist),
            }
            for s in sorted(result.spaces, key=lambda x: (x.name == "Unidentified space", x.category.value, x.name))
        ],
        "set_aside": [vars(item) for item in result.not_rooms],
    }


def analysis_text(result: Analysis) -> str:
    identified = [s for s in result.spaces if s.name != "Unidentified space"]
    lines = [
        f"{Path(result.source).name}, page {result.page}: route {result.route}. "
        f"{len(identified)} spaces identified, {len(result.spaces) - len(identified)} unidentified, "
        f"{len(result.not_rooms)} areas set aside.",
        result.scale_note,
    ]
    if result.naming_error:
        lines.append(result.naming_error)
    lines.append("All names are unreviewed. An engineer must confirm them. No FAIL is possible until then.\n")
    for space in sorted(result.spaces, key=lambda s: (s.category.value, s.name)):
        printed = "printed on drawing" if space.name_on_drawing else "NOT confirmed as printed"
        area = f", {space.area_m2:.1f} m2" if space.area_m2 is not None else ""
        number = f" {space.compartment}" if space.compartment else ""
        lines.append(f"#{space.number} {space.name}{number} [{space.category.value}]{area}, confidence {space.confidence:.2f}, {printed}")
        for item in space.checklist:
            mark = "" if item.confirmed_reference else " (reference not yet confirmed)"
            lines.append(f"    check: {item.ref}: {item.what}{mark}")
            if item.finding:
                lines.append(f"      measured, {item.finding.verdict.value}: {item.finding.why}")
    if result.not_rooms:
        lines.append("\nSet aside, for the engineer to glance over:")
        for item in result.not_rooms:
            lines.append(f"  #{item.number} {item.description}: {item.reason}")
    return "\n".join(lines)
