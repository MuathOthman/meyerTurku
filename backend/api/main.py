"""Thin web layer over the Keel library. No compliance logic lives here."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import cv2
import pymupdf
import yaml
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response

from pydantic import BaseModel, Field

from keel.analyze import analysis_json, analyze, rename_space, space_types
from keel.checks import run_checks
from keel.decisions import DecisionInput, add_decision, read_decisions
from keel.evaluate import evaluate, load_cases
from keel.extract import extract_page
from keel.explain import add_explanations
from keel.impact import cabin_impact, load_impact_map
from keel.inject import apply_defect
from keel.llm import get_llm
from keel.model import Deck
from keel.pipeline import build_deck
from keel.projects import DEFAULT_PROJECT, ProjectInput, add_project, get_project, read_projects, set_rule_selection
from keel.report import sort_findings
from keel.rules import SHIP_TYPES, load_rules
from keel.sheet import DeckPlan, SheetScale, find_deck_plans, sheet_scale
from keel.sources import (
    SourceInput,
    add_source,
    delete_source,
    read_sources,
    source_file,
)
from keel.verdict import Verdict

BACKEND = Path(__file__).resolve().parents[1]
CONFIG = Path(os.environ.get("KEEL_DECK_CONFIG", BACKEND / "data/decks/rcrv_01_level.yaml"))
DECK_JSON = Path(os.environ.get("KEEL_DECK_JSON", BACKEND / "data/processed/deck01.json"))
CASES = BACKEND / "data/decks/rcrv_01_level_eval.yaml"
RULES = BACKEND / "rules"
IMPACT_MAP = BACKEND / "config/impact_map.yaml"
# The built React app (frontend/). During development Vite serves it and proxies /api here.
FRONTEND = Path(os.environ.get("KEEL_FRONTEND_DIST", BACKEND.parent / "frontend/dist"))
DECISIONS = BACKEND / "data/processed/decisions.json"
SOURCES = BACKEND / "data/processed/sources"
# Projects, each with the rules the engineer chose. Findings on other rules are not shown.
PROJECTS = BACKEND / "data/processed/projects.json"

log = logging.getLogger(__name__)

app = FastAPI(title="Keel", description="AI reads, code measures, engineer decides.")


@lru_cache(maxsize=1)
def get_deck() -> Deck:
    if DECK_JSON.exists():
        return Deck.model_validate_json(DECK_JSON.read_text())
    deck, _ = build_deck(CONFIG, get_llm())
    DECK_JSON.parent.mkdir(parents=True, exist_ok=True)
    DECK_JSON.write_text(deck.model_dump_json())
    return deck


@lru_cache(maxsize=1)
def get_config() -> dict:
    return yaml.safe_load(CONFIG.read_text())


def scenarios() -> list[dict]:
    return [c for c in load_cases(CASES) if c.get("kind", "defect") == "defect"]


def scenario_deck(name: str | None) -> Deck:
    deck = get_deck()
    if not name:
        return deck
    for case in scenarios():
        if case["name"] == name:
            return apply_defect(deck, case["defect"], case.get("args", {}))
    raise HTTPException(404, f"unknown scenario {name!r}")


UPLOAD_TYPES = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
MAX_UPLOAD_BYTES = 80 * 1024 * 1024
RESULTS = BACKEND / "data/processed/analyses"


# Analyses run one at a time: each uses a lot of CPU, and a second upload simply waits its turn.
ANALYSIS_QUEUE = ThreadPoolExecutor(max_workers=1)
JOBS: dict[str, dict] = {}


def _read_scale(path: Path, page: int, plans: list[DeckPlan]) -> SheetScale | None:
    """A sheet without a readable scale is normal, not an error."""
    try:
        with pymupdf.open(path) as document:
            segments = extract_page(document[page]).segments
        return sheet_scale(path, page, segments, plans)
    except (RuntimeError, ValueError, IndexError) as error:
        log.info("No scale read from %s: %s", path.name, error)
        return None


def run_analysis(
    job: str,
    path: Path,
    page: int,
    mm_per_unit: float | None,
    use_ai: bool,
    source: str,
    ship_type: str = "passenger",
    region: tuple | None = None,
    plans: list | None = None,
    upload_name: str | None = None,
) -> None:
    state = JOBS[job]

    def on_step(step: str, detail: str) -> None:
        if state["step"] and step != state["step"]:
            state["completed"] = [*state["completed"], state["step"]]
        state.update(step=step, detail=detail)

    state.update(step="", completed=[])
    try:
        relative_error, note = 0.005, None
        if mm_per_unit is None and path.suffix.lower() == ".pdf":
            on_step("Reading the scale from the sheet", "")
            found = _read_scale(path, page, plans or [])
            if found is not None:
                mm_per_unit, relative_error, note = found.mm_per_pt, found.relative_error, found.note
        result = analyze(
            path, get_llm() if use_ai else None, page, region, mm_per_unit, on_step=on_step,
            ship_type=ship_type, relative_error=relative_error, scale_note_override=note,
        )
        folder = path.parent
        cv2.imwrite(str(folder / "numbered.jpg"), result.annotated, [cv2.IMWRITE_JPEG_QUALITY, 88])
        cv2.imwrite(str(folder / "plan.jpg"), result.plan, [cv2.IMWRITE_JPEG_QUALITY, 90])
        body = analysis_json(result)
        for finding in body.get("findings", []):
            finding["source_pdf"] = upload_name or source
        body.update(
            id=job,
            source=source,
            image=f"/api/analyze/{job}/numbered.jpg",
            plan_image=f"/api/analyze/{job}/plan.jpg",
            deck=state.get("deck"),
            project=state.get("project", DEFAULT_PROJECT),
            created_at=state["created_at"],
        )
        temporary = folder / "result.tmp"
        temporary.write_text(json.dumps(body))
        temporary.replace(folder / "result.json")
        state["status"] = "done"
    except (ValueError, IndexError) as error:
        state.update(status="failed", error=f"Could not read this drawing: {error}")
    except Exception:
        log.exception("Analysis %s failed", job)
        state.update(status="failed", error="The analysis failed unexpectedly. The server log has the details.")
    if state["status"] == "failed":
        shutil.rmtree(path.parent, ignore_errors=True)


@app.post("/api/analyze", status_code=202)
def analyze_upload(
    file: UploadFile = File(...),
    page: int = Form(0),
    mm_per_unit: float | None = Form(None),
    use_ai: bool = Form(True),
    ship_type: str = Form("passenger"),
    project: str = Form(DEFAULT_PROJECT),
) -> dict:
    """Store an uploaded drawing under a generated name and queue it. Poll .../status for progress."""
    if get_project(PROJECTS, project) is None:
        raise HTTPException(404, f"No project {project!r}.")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in UPLOAD_TYPES:
        raise HTTPException(400, f"Unsupported file type. Use one of: {sorted(UPLOAD_TYPES)}")
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is larger than 80 MB.")
    if ship_type not in SHIP_TYPES:
        raise HTTPException(422, f"Ship type must be one of: {list(SHIP_TYPES)}")
    created = datetime.now(timezone.utc).isoformat()

    def queue(deck: DeckPlan | None, plans: list[DeckPlan]) -> dict:
        job = uuid.uuid4().hex
        folder = RESULTS / job
        folder.mkdir(parents=True)
        path = folder / f"input{suffix}"
        path.write_bytes(data)
        name = f"{deck.name} · {file.filename}" if deck else file.filename
        JOBS[job] = {
            "id": job,
            "status": "running",
            "step": "Waiting for another drawing to finish",
            "detail": "",
            "completed": [],
            "error": None,
            "source": name,
            "deck": deck.name if deck else None,
            "project": project,
            "page": page,
            "created_at": created,
        }
        ANALYSIS_QUEUE.submit(
            run_analysis, job, path, page, mm_per_unit, use_ai, name, ship_type, deck.region if deck else None, plans, file.filename
        )
        return JOBS[job]

    plans = _plans_on_sheet(data, suffix, page)
    jobs = [queue(plan, plans) for plan in plans] or [queue(None, [])]
    return {**jobs[0], "jobs": [j["id"] for j in jobs]}


def _plans_on_sheet(data: bytes, suffix: str, page: int) -> list[DeckPlan]:
    """A sheet of several decks becomes one checked deck each. A single plan stays whole."""
    if suffix != ".pdf":
        return []
    with tempfile.NamedTemporaryFile(suffix=suffix) as copy:
        copy.write(data)
        copy.flush()
        try:
            plans = find_deck_plans(copy.name, page)
        except (ValueError, IndexError, RuntimeError):
            return []
    return plans if len(plans) >= 2 else []


@app.get("/api/analyze/{job}/status")
def analysis_status(job: str) -> dict:
    if job in JOBS:
        return JOBS[job]
    if (job_folder(job) / "result.json").is_file():
        return {"id": job, "status": "done"}
    raise HTTPException(404, "This analysis did not finish, possibly because the server restarted.")


def job_folder(job: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", job):
        raise HTTPException(404)
    folder = RESULTS / job
    if not folder.is_dir():
        raise HTTPException(404)
    return folder


@app.get("/api/analyses")
def list_analyses() -> list[dict]:
    """Running and saved analyses, newest first. An abandoned run has no result.json and is skipped."""
    summaries = [
        {
            **{k: job[k] for k in ("id", "source", "deck", "project", "page", "created_at", "status")},
            "ship_type": None,
            "identified": 0,
            "unidentified": 0,
            "counts": None,
        }
        for job in JOBS.values()
        if job["status"] == "running"
    ]
    for path in RESULTS.glob("*/result.json") if RESULTS.is_dir() else []:
        body = json.loads(path.read_text())
        unidentified = sum(s["name"] == "Unidentified space" for s in body["spaces"])
        owner = body.get("project", DEFAULT_PROJECT)
        measured = [f for f in _selected(body.get("findings") or [], owner) if not f.get("could_not_check")]
        summaries.append(
            {
                "id": body["id"],
                "source": body["source"],
                "deck": body.get("deck"),
                "project": owner,
                "page": body["page"],
                "created_at": body["created_at"],
                "status": "done",
                "ship_type": body.get("ship_type"),
                "identified": len(body["spaces"]) - unidentified,
                "unidentified": unidentified,
                "counts": {v: sum(f["verdict"] == v for f in measured) for v in ("FAIL", "NEEDS_REVIEW", "PASS")},
            }
        )
    return sorted(summaries, key=lambda s: s["created_at"], reverse=True)


@app.get("/api/analyze/{job}")
def get_analysis(job: str) -> dict:
    path = job_folder(job) / "result.json"
    if not path.is_file():
        raise HTTPException(404)
    body = json.loads(path.read_text())
    body.setdefault("project", DEFAULT_PROJECT)
    if body.get("findings") is not None:
        body["findings"] = _selected(body["findings"], body["project"])
    return body


@app.delete("/api/analyze/{job}", status_code=204)
def delete_analysis(job: str) -> None:
    folder = job_folder(job)
    if JOBS.get(job, {}).get("status") == "running":
        raise HTTPException(409, "This analysis is still running.")
    JOBS.pop(job, None)
    shutil.rmtree(folder)


@app.get("/api/analyze/{job}/numbered.jpg")
def analyze_image(job: str) -> FileResponse:
    path = job_folder(job) / "numbered.jpg"
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg")


@app.get("/api/analyze/{job}/plan.jpg")
def analyze_plan(job: str) -> FileResponse:
    path = job_folder(job) / "plan.jpg"
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg")


class SpaceCorrection(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: str | None = None


_saved_result_lock = threading.Lock()


@app.patch("/api/analyze/{job}/spaces/{number}")
def correct_space(job: str, number: int, correction: SpaceCorrection) -> dict:
    """An engineer names a space or confirms its name. Returns the whole updated result."""
    name = correction.name.strip()
    if not name:
        raise HTTPException(422, "A space needs a name.")
    path = job_folder(job) / "result.json"
    with _saved_result_lock:
        if not path.is_file():
            raise HTTPException(404)
        body = json.loads(path.read_text())
        index = next((i for i, s in enumerate(body["spaces"]) if s["number"] == number), None)
        if index is None:
            raise HTTPException(404, f"No space number {number} in this drawing.")
        old = body["spaces"][index]
        try:
            body["spaces"][index] = rename_space(old, name, correction.category)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(body))
        temporary.replace(path)
    new = body["spaces"][index]
    add_decision(
        DECISIONS,
        DecisionInput(
            finding=f"{job}:{number}",
            rule_id=body["source"][:100],
            subject=new["name"],
            decision="renamed",
            note=f'Was "{old["name"]}" ({old["category"]}), now "{new["name"]}" ({new["category"]})',
        ),
    )
    return body


@app.get("/api/rules/{ship_type}")
def rules_for_ship(ship_type: str) -> list[dict]:
    if ship_type not in SHIP_TYPES:
        raise HTTPException(404)
    return [rule.model_dump() for rule in load_rules(RULES, ship_type=ship_type)]


@app.get("/api/space-types")
def list_space_types() -> list[str]:
    return space_types()


@app.get("/api/rules")
def rules() -> list[dict]:
    return [rule.model_dump() for rule in load_rules(RULES)]


@app.get("/api/decisions")
def decisions() -> list[dict]:
    return [d.model_dump() for d in read_decisions(DECISIONS)]


@app.post("/api/decisions", status_code=201)
def record_decision(entry: DecisionInput) -> dict:
    return add_decision(DECISIONS, entry).model_dump()


def _chosen_rules(project_id: str) -> list[str] | None:
    project = get_project(PROJECTS, project_id)
    return project.rule_ids if project else None


def _selected(findings: list[dict], project_id: str) -> list[dict]:
    """Saved findings on the rules the project checks."""
    chosen = _chosen_rules(project_id)
    return findings if chosen is None else [f for f in findings if f["rule_id"] in chosen]


@app.get("/api/sources")
def list_sources() -> list[dict]:
    return [s.model_dump() for s in read_sources(SOURCES)]


@app.post("/api/sources", status_code=201)
def create_source(
    title: str = Form(...),
    url: str = Form(""),
    pages: str = Form(""),
    note: str = Form(""),
    rule_ids: str = Form(""),
    file: UploadFile | None = File(None),
) -> dict:
    """A regulation file, a link or a note, with the pages that matter and the rules it backs."""
    data = file.file.read(MAX_UPLOAD_BYTES + 1) if file and file.filename else None
    if data is not None and len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is larger than 80 MB.")
    known = {r.id for r in load_rules(RULES)}
    ids = [i.strip() for i in rule_ids.split(",") if i.strip()]
    if unknown := [i for i in ids if i not in known]:
        raise HTTPException(422, f"Unknown rules: {unknown}")
    try:
        entry = SourceInput(title=title.strip(), url=url.strip(), pages=pages.strip(), note=note.strip(), rule_ids=ids)
        return add_source(SOURCES, entry, file.filename if data is not None else None, data).model_dump()
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


def _source(source_id: str):
    found = next((s for s in read_sources(SOURCES) if s.id == source_id), None)
    if found is None:
        raise HTTPException(404)
    return found


@app.get("/api/sources/{source_id}/file")
def get_source_file(source_id: str) -> FileResponse:
    source = _source(source_id)
    path = source_file(SOURCES, source)
    if path is None:
        raise HTTPException(404)
    # Inline, so a PDF opens in the browser at the page the engineer asks for.
    return FileResponse(path, filename=source.file_name, content_disposition_type="inline")


@app.delete("/api/sources/{source_id}", status_code=204)
def remove_source(source_id: str) -> None:
    if not delete_source(SOURCES, source_id):
        raise HTTPException(404)


class RuleSelection(BaseModel):
    rule_ids: list[str] = Field(max_length=500)


@app.get("/api/projects")
def list_projects() -> list[dict]:
    """Oldest first. rule_ids is null while every rule is checked."""
    return [p.model_dump() for p in read_projects(PROJECTS)]


@app.post("/api/projects", status_code=201)
def create_project(entry: ProjectInput) -> dict:
    if entry.ship_type not in SHIP_TYPES:
        raise HTTPException(422, f"Ship type must be one of: {list(SHIP_TYPES)}")
    try:
        return add_project(PROJECTS, entry).model_dump()
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@app.put("/api/projects/{project_id}/rules")
def set_project_rules(project_id: str, selection: RuleSelection) -> dict:
    project = get_project(PROJECTS, project_id)
    if project is None:
        raise HTTPException(404)
    known = {r.id for r in load_rules(RULES, ship_type=project.ship_type)}
    if unknown := [i for i in selection.rule_ids if i not in known]:
        raise HTTPException(422, f"Unknown rules: {unknown}")
    return set_rule_selection(PROJECTS, project_id, selection.rule_ids).model_dump()


@app.get("/api/meta")
def meta() -> dict:
    deck = get_deck()
    llm = get_llm()
    return {
        "deck": deck.name,
        "source_pdf": deck.source_pdf,
        "page_index": deck.page_index,
        "mm_per_pt": deck.mm_per_pt,
        "calibration": deck.calibration_note,
        "tolerance_mm": deck.tolerance_mm(1000),
        "spaces": len(deck.spaces),
        "doors": len(deck.doors),
        "unresolved_arcs": len(deck.unresolved_arcs_mm),
        "region": get_config()["plan_region"],
        "scenarios": [c["name"] for c in scenarios()],
        "llm": llm.name if llm else None,
    }


@app.get("/api/drawing.png")
def drawing() -> Response:
    return Response(_render_drawing(), media_type="image/png", headers={"Cache-Control": "max-age=3600"})


@lru_cache(maxsize=1)
def _render_drawing() -> bytes:
    deck = get_deck()
    with pymupdf.open(BACKEND / "data/raw" / deck.source_pdf) as document:
        clip = pymupdf.Rect(*get_config()["plan_region"])
        return document[deck.page_index].get_pixmap(dpi=300, clip=clip).tobytes("png")


@app.get("/api/findings")
def findings(
    scenario: str | None = None,
    scope: str | None = None,
    explain: bool = False,
) -> dict:
    deck = scenario_deck(scenario)
    # The demo deck belongs to the default project.
    chosen = _chosen_rules(DEFAULT_PROJECT)
    results = run_checks(deck, [r for r in load_rules(RULES, scope) if chosen is None or r.id in chosen])
    note_error = None
    if explain:
        llm = get_llm()
        if llm is None:
            note_error = "No LLM is configured."
        else:
            add_explanations(results, llm)
    counts = {v.value: sum(f.verdict == v for f in results) for v in Verdict}
    return {
        "counts": counts,
        "injected": deck.injected,
        "note_error": note_error,
        "findings": [f.model_dump(mode="json") for f in sort_findings(results)],
    }


@app.get("/api/spaces")
def spaces() -> list[dict]:
    deck = get_deck()
    return [
        {
            "id": s.id,
            "name": s.name,
            "category": s.category.value,
            "area_m2": round(s.area_m2, 1),
            "outline_pt": [(x / deck.mm_per_pt, y / deck.mm_per_pt) for x, y in s.exterior_mm],
        }
        for s in deck.spaces
    ]


@app.get("/api/eval")
def run_eval() -> dict:
    report = evaluate(get_deck(), load_rules(RULES), load_cases(CASES))
    return {
        "baseline": {"FAIL": report.baseline_fail, "NEEDS_REVIEW": report.baseline_review, "PASS": report.baseline_pass},
        "defects_total": len(report.defects),
        "defects_found": report.found,
        "controls_total": len(report.controls),
        "false_alarms": report.false_alarms,
        "cases": [vars(c) for c in report.cases],
    }


@app.get("/api/impact")
def impact(count: int = Query(6, ge=1, le=200), berths_each: int = Query(2, ge=1, le=6)) -> dict:
    deck = get_deck()
    result = cabin_impact(deck, load_rules(RULES), load_impact_map(IMPACT_MAP), count, berths_each, None)
    capacity = next((f for f in result.findings if f.rule_id == "ESC-STAIR-CAPACITY"), None)
    return {
        "count": result.count,
        "persons_added": result.persons_added,
        "persons_total": result.persons_total,
        "stair_capacity": capacity.model_dump(mode="json") if capacity else None,
        "newly_failing": [f.model_dump(mode="json") for f in result.newly_failing],
        "rules_that_apply": result.rules_that_apply,
        "notify": result.notify,
    }


# Registered last, so every /api route above wins. Anything else is a file of the React app,
# or one of its client-side routes, which the app itself resolves from index.html.
@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str) -> FileResponse:
    root = FRONTEND.resolve()
    target = (root / path).resolve()
    if path.startswith("api/"):
        raise HTTPException(404)
    if not (root / "index.html").is_file():
        raise HTTPException(404, "The web app is not built. Run: npm --prefix frontend run build")
    if target.is_file() and target.is_relative_to(root):
        return FileResponse(target)
    # A missing asset is an error. Only page URLs fall through to the app.
    if path.startswith("assets/"):
        raise HTTPException(404)
    return FileResponse(root / "index.html")
