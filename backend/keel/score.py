"""Score an analysis against a hand-written answer key."""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

import yaml

from keel.analyze import Analysis, _compact


@dataclass
class Score:
    rooms_total: int = 0
    space_found: int = 0
    name_correct: int = 0
    category_correct: int = 0
    not_rooms_total: int = 0
    not_rooms_correct: int = 0
    wrong: list[str] = field(default_factory=list)


def _px(result: Analysis, anchor, unit_per_page_point: float = 1.0) -> tuple[int, int]:
    """Anchors are PDF page points. An image export is scaled by its pixels per point."""
    x0, y0 = result.region[:2] if result.region else (0, 0)
    scale = result.px_per_unit * unit_per_page_point
    return int((anchor[0] - x0) * scale), int((anchor[1] - y0) * scale)


def score(result: Analysis, truth_path: str | Path, unit_per_page_point: float = 1.0) -> Score:
    truth = yaml.safe_load(Path(truth_path).read_text())
    by_number = {s.number: s for s in result.spaces}
    report = Score()
    height, width = result.labels.shape

    def at(anchor) -> int:
        x, y = _px(result, anchor, unit_per_page_point)
        return int(result.labels[y, x]) if 0 <= y < height and 0 <= x < width else 0

    for room in truth["rooms"]:
        report.rooms_total += 1
        label = room["accept"][0]
        number = at(room["anchor"])
        if number == 0:
            report.wrong.append(f"{label}: no space found")
            continue
        space = by_number.get(number)
        if space is None:
            report.wrong.append(f"{label}: wrongly set aside as furniture (#{number})")
            continue
        report.space_found += 1
        name = _compact(space.name)
        if any(_compact(a) in name or SequenceMatcher(None, _compact(a), name).ratio() >= 0.85 for a in room["accept"]):
            report.name_correct += 1
        else:
            report.wrong.append(f"{label}: named '{space.name}' (#{number})")
        wanted = room["category"] if isinstance(room["category"], list) else [room["category"]]
        if space.category.value in wanted:
            report.category_correct += 1
        else:
            report.wrong.append(f"{label}: category {space.category.value}, expected {'/'.join(wanted)}")
    for anchor in truth.get("not_rooms", []):
        report.not_rooms_total += 1
        number = at(anchor)
        if number == 0 or number not in by_number:
            report.not_rooms_correct += 1
        else:
            report.wrong.append(f"Furniture at {anchor} named as a room: '{by_number[number].name}'")
    return report
