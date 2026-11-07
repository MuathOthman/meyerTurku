"""Projects: one ship each, with its ship type and the rules the engineer chose for it.

Floors (saved analyses) name their project. Anything saved before projects existed belongs to the
default project, which also holds the built-in demo deck.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

DEFAULT_PROJECT = "default"


class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    ship_type: str = Field(min_length=1, max_length=40)


class Project(ProjectInput):
    id: str
    created_at: str
    # The rule ids this project checks. None until an engineer chooses, which means every rule.
    rule_ids: list[str] | None = None


_lock = threading.Lock()

_DEFAULT = Project(id=DEFAULT_PROJECT, name="Cruise ship NB [####]", ship_type="passenger", created_at="")


def read_projects(path: Path) -> list[Project]:
    """Oldest first. The default project is always there."""
    stored = [Project(**p) for p in json.loads(path.read_text())] if path.exists() else []
    return stored if any(p.id == DEFAULT_PROJECT for p in stored) else [_DEFAULT, *stored]


def get_project(path: Path, project_id: str) -> Project | None:
    return next((p for p in read_projects(path) if p.id == project_id), None)


def _write(path: Path, projects: list[Project]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps([p.model_dump() for p in projects], indent=1))
    temporary.replace(path)


def _slug(name: str, taken: set[str]) -> str:
    """A readable id for URLs: "Cruise ship NB 1234" → "cruise-ship-nb-1234"."""
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "project"
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    return slug


def add_project(path: Path, entry: ProjectInput) -> Project:
    with _lock:
        projects = read_projects(path)
        if any(p.name.casefold() == entry.name.strip().casefold() for p in projects):
            raise ValueError(f"A project called {entry.name.strip()!r} already exists.")
        project = Project(
            name=entry.name.strip(),
            ship_type=entry.ship_type,
            id=_slug(entry.name, {p.id for p in projects}),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        _write(path, [*projects, project])
    return project


def set_rule_selection(path: Path, project_id: str, rule_ids: list[str]) -> Project:
    with _lock:
        projects = read_projects(path)
        index = next((i for i, p in enumerate(projects) if p.id == project_id), None)
        if index is None:
            raise KeyError(project_id)
        projects[index] = projects[index].model_copy(update={"rule_ids": sorted(set(rule_ids))})
        _write(path, projects)
    return projects[index]
