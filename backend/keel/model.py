"""The neutral ship model. Everything is in millimetres, independent of the source format.

Checks read only this model, never the PDF. A later OCX, IFC or Navisworks importer only
has to produce a Deck to reuse every check.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field
from shapely.geometry import Polygon

PointMM = tuple[float, float]


class Category(str, Enum):
    CABIN = "cabin"
    CORRIDOR = "corridor"
    STAIR = "stair"
    OPEN_DECK = "open_deck"
    MEDICAL = "medical"
    SERVICE = "service"
    MACHINERY = "machinery"
    GALLEY = "galley"
    LAB = "lab"
    STORES = "stores"
    SANITARY = "sanitary"
    PUBLIC = "public"
    CONTROL = "control"
    UNKNOWN = "unknown"


class Space(BaseModel):
    id: str
    name: str
    compartment: str | None = None
    category: Category = Category.UNKNOWN
    classification_confidence: float = 0.0
    label_source: str = "none"  # ocr_leader | ocr_in_room | reviewed | none
    anchor_mm: PointMM
    exterior_mm: list[PointMM]
    interiors_mm: list[list[PointMM]] = Field(default_factory=list)
    berths: int = 0
    accessible: bool = False

    def polygon(self) -> Polygon:
        return Polygon(self.exterior_mm, self.interiors_mm)

    @property
    def area_m2(self) -> float:
        return self.polygon().area / 1e6


class Door(BaseModel):
    id: str
    hinge_mm: PointMM
    latch_mm: PointMM
    leaf_tip_mm: PointMM
    arc_mid_mm: PointMM
    leaf_width_mm: float
    space_a: str | None = None
    space_b: str | None = None
    swings_into: str | None = None
    direction_confident: bool = True

    def other_side(self, space_id: str) -> str | None:
        if space_id == self.space_a:
            return self.space_b
        if space_id == self.space_b:
            return self.space_a
        return None

    @property
    def midpoint_mm(self) -> PointMM:
        return (
            (self.hinge_mm[0] + self.latch_mm[0]) / 2,
            (self.hinge_mm[1] + self.latch_mm[1]) / 2,
        )


class Deck(BaseModel):
    name: str
    source_pdf: str
    page_index: int
    mm_per_pt: float
    relative_error: float
    extraction_tolerance_mm: float
    calibration_note: str = ""
    spaces: list[Space] = Field(default_factory=list)
    doors: list[Door] = Field(default_factory=list)
    unresolved_arcs_mm: list[PointMM] = Field(default_factory=list)
    persons_other_decks: int = 0
    injected: list[str] = Field(default_factory=list)

    def tolerance_mm(self, length_mm: float) -> float:
        return abs(length_mm) * self.relative_error + self.extraction_tolerance_mm

    def space(self, space_id: str) -> Space:
        for s in self.spaces:
            if s.id == space_id:
                return s
        raise KeyError(f"no space with id {space_id}")

    def door(self, door_id: str) -> Door:
        for d in self.doors:
            if d.id == door_id:
                return d
        raise KeyError(f"no door with id {door_id}")

    def doors_of(self, space_id: str) -> list[Door]:
        return [d for d in self.doors if space_id in (d.space_a, d.space_b)]

    def by_category(self, *categories: Category) -> list[Space]:
        return [s for s in self.spaces if s.category in categories]

    @property
    def total_berths(self) -> int:
        return sum(s.berths for s in self.spaces)
