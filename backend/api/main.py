"""Thin web layer over the Keel library. No compliance logic lives here."""
from __future__ import annotations

import os
import re
import uuid
from functools import lru_cache
from pathlib import Path

import cv2
import pymupdf
import yaml
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response

from keel.analyze import analysis_json, analyze
from keel.checks import run_checks
from keel.evaluate import evaluate, load_cases
from keel.explain import add_explanations
from keel.impact import cabin_impact, load_impact_map
from keel.inject import apply_defect
from keel.llm import get_llm
from keel.model import Deck
from keel.pipeline import build_deck
from keel.report import sort_findings
from keel.rules import load_rules
from keel.verdict import Verdict

BACKEND = Path(__file__).resolve().parents[1]
CONFIG = Path(os.environ.get("KEEL_DECK_CONFIG", BACKEND / "data/decks/rcrv_01_level.yaml"))
DECK_JSON = Path(os.environ.get("KEEL_DECK_JSON", BACKEND / "data/processed/deck01.json"))
CASES = BACKEND / "data/decks/rcrv_01_level_eval.yaml"
RULES = BACKEND / "rules"
IMPACT_MAP = BACKEND / "config/impact_map.yaml"
WEB = BACKEND / "web"

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


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


@app.get("/analyze")
def analyze_page() -> FileResponse:
    return FileResponse(WEB / "analyze.html")


UPLOAD_TYPES = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
MAX_UPLOAD_BYTES = 80 * 1024 * 1024
RESULTS = BACKEND / "data/processed/analyses"


@app.post("/api/analyze")
def analyze_upload(
    file: UploadFile = File(...),
    page: int = Form(0),
    mm_per_unit: float | None = Form(None),
    use_ai: bool = Form(True),
) -> dict:
    """Analyse an uploaded drawing. The file is stored under a generated name."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in UPLOAD_TYPES:
        raise HTTPException(400, f"Unsupported file type. Use one of: {sorted(UPLOAD_TYPES)}")
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is larger than 80 MB.")
    job = uuid.uuid4().hex
    folder = RESULTS / job
    folder.mkdir(parents=True)
    path = folder / f"input{suffix}"
    path.write_bytes(data)
    try:
        result = analyze(path, get_llm() if use_ai else None, page, None, mm_per_unit)
    except (ValueError, IndexError) as error:
        raise HTTPException(422, f"Could not read this drawing: {error}") from error
    cv2.imwrite(str(folder / "numbered.jpg"), result.annotated, [cv2.IMWRITE_JPEG_QUALITY, 88])
    body = analysis_json(result)
    body["source"] = file.filename
    body["image"] = f"/api/analyze/{job}/numbered.jpg"
    return body


@app.get("/api/analyze/{job}/numbered.jpg")
def analyze_image(job: str) -> FileResponse:
    if not re.fullmatch(r"[0-9a-f]{32}", job):
        raise HTTPException(404)
    path = RESULTS / job / "numbered.jpg"
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg")


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
    results = run_checks(deck, load_rules(RULES, scope))
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
