"""The engineer's decisions on findings. An append-only log, so the history is never rewritten.

A decision never changes a verdict. Verdicts come only from keel/verdict.py.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class DecisionInput(BaseModel):
    finding: str = Field(min_length=1, max_length=300)
    rule_id: str = Field(min_length=1, max_length=100)
    subject: str = Field(min_length=1, max_length=300)
    # complies / does_not_comply record a regulation an engineer checked by hand.
    decision: Literal["accepted", "need_info", "rejected", "cleared", "renamed", "complies", "does_not_comply"]
    note: str = Field(default="", max_length=2000)


class Decision(DecisionInput):
    at: str


_lock = threading.Lock()


def read_decisions(path: Path) -> list[Decision]:
    """Oldest first."""
    if not path.exists():
        return []
    return [Decision(**entry) for entry in json.loads(path.read_text())]


def add_decision(path: Path, entry: DecisionInput) -> Decision:
    decision = Decision(**entry.model_dump(), at=datetime.now(timezone.utc).isoformat())
    with _lock:
        log = read_decisions(path) + [decision]
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write then swap, so a crash cannot leave a half-written log.
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps([d.model_dump() for d in log], indent=1))
        temporary.replace(path)
    return decision
