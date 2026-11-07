"""Rule sources engineers add: a regulation PDF, a web page, or a note, with the pages that matter.

A source backs rules; it never changes a limit. Limits live in rules/*.yaml.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

SOURCE_FILE_TYPES = {".pdf", ".png", ".jpg", ".jpeg", ".txt", ".md", ".doc", ".docx", ".xlsx"}


class SourceInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    url: str = Field(default="", max_length=2000)
    pages: str = Field(default="", max_length=200)  # As engineers write them: "12-14, 31".
    note: str = Field(default="", max_length=4000)
    rule_ids: list[str] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def _url_is_web(self) -> SourceInput:
        if self.url and not self.url.startswith(("http://", "https://")):
            raise ValueError("A link must start with http:// or https://")
        return self


class Source(SourceInput):
    id: str
    file_name: str | None = None
    added_at: str


_lock = threading.Lock()


def read_sources(folder: Path) -> list[Source]:
    """Oldest first."""
    index = folder / "sources.json"
    if not index.exists():
        return []
    return [Source(**entry) for entry in json.loads(index.read_text())]


def _write(folder: Path, sources: list[Source]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / "sources.tmp"
    temporary.write_text(json.dumps([s.model_dump() for s in sources], indent=1))
    temporary.replace(folder / "sources.json")


def add_source(folder: Path, entry: SourceInput, file_name: str | None = None, data: bytes | None = None) -> Source:
    if not (entry.url or data or entry.note):
        raise ValueError("A source needs a file, a link or a note.")
    suffix = Path(file_name or "").suffix.lower()
    if data is not None and suffix not in SOURCE_FILE_TYPES:
        raise ValueError(f"Unsupported file type. Use one of: {sorted(SOURCE_FILE_TYPES)}")
    source = Source(
        **entry.model_dump(),
        id=uuid.uuid4().hex,
        file_name=file_name if data is not None else None,
        added_at=datetime.now(timezone.utc).isoformat(),
    )
    with _lock:
        if data is not None:
            stored = folder / "files" / f"{source.id}{suffix}"
            stored.parent.mkdir(parents=True, exist_ok=True)
            stored.write_bytes(data)
        _write(folder, read_sources(folder) + [source])
    return source


def source_file(folder: Path, source: Source) -> Path | None:
    if not source.file_name:
        return None
    path = folder / "files" / f"{source.id}{Path(source.file_name).suffix.lower()}"
    return path if path.is_file() else None


def delete_source(folder: Path, source_id: str) -> bool:
    with _lock:
        sources = read_sources(folder)
        kept = [s for s in sources if s.id != source_id]
        if len(kept) == len(sources):
            return False
        gone = next(s for s in sources if s.id == source_id)
        path = source_file(folder, gone)
        if path:
            path.unlink()
        _write(folder, kept)
    return True

