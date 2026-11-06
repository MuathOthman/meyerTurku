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
    value_status: Literal["verified", "assumed"]
    check: str
    interpretation_note: str = ""


def load_rules(path: str | Path, scope: str | None = None) -> list[Rule]:
    """Load every *.yaml file in a folder, or one file. Duplicate ids are an error."""
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
    return [r for r in rules if scope is None or r.scope == scope]
