"""Load and validate the rule database from YAML files."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    source: str
    ref_url: str = ""
    type: Literal["numeric", "geometric", "judgment"]
    scope: str
    applies_to: list[str]
    parameter: str
    operator: Literal[">=", "<="] | None = None
    value_mm: float | None = None
    value_mm_per_person: float | None = None
    minimum_routes: int | None = None
    minimum_area_m2: float | None = None
    value_status: Literal["verified", "assumed"]
    check: str
    interpretation_note: str = ""
    why_it_matters: str = ""
    fix: str = ""  # May use {shortfall} and {required}, both in mm.
    ship_values: dict[str, dict] | None = None  # Limits that differ by ship type.
    ship_types: list[str] | None = None  # Only these ship types, when the source says so.


SHIP_TYPES = ("passenger", "cargo")


def load_rules(path: str | Path, scope: str | None = None, ship_type: str = "passenger") -> list[Rule]:
    """Load every *.yaml file in a folder, or one file. Duplicate ids are an error.

    A rule with ship_values takes its limit and source from the given ship type.
    """
    path = Path(path)
    files = sorted(path.glob("*.yaml")) if path.is_dir() else [path]
    rules: list[Rule] = []
    for file in files:
        for entry in yaml.safe_load(file.read_text()) or []:
            rules.append(Rule(**entry))
    ids = [r.id for r in rules]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate rule ids: {sorted(duplicates)}")
    chosen = [
        r for r in rules
        if (scope is None or r.scope == scope) and (r.ship_types is None or ship_type in r.ship_types)
    ]
    return [
        r.model_copy(update=r.ship_values[ship_type]) if r.ship_values and ship_type in r.ship_values else r
        for r in chosen
    ]
