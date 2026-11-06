"""Keel command line. Run `keel --help`."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from keel.checks import run_checks
from keel.evaluate import evaluate, load_cases
from keel.explain import add_explanations
from keel.impact import cabin_impact, load_impact_map
from keel.inject import apply_defect
from keel.llm import get_llm
from keel.model import Deck
from keel.pipeline import build_deck
from keel.report import annotate, eval_table, findings_json, findings_table
from keel.rules import load_rules

app = typer.Typer(add_completion=False, help="Keel: AI reads, code measures, engineer decides.")

BACKEND = Path(__file__).resolve().parents[1]
DEFAULT_RULES = BACKEND / "rules"
DEFAULT_MAP = BACKEND / "config" / "impact_map.yaml"
RAW = BACKEND / "data" / "raw"


def _load(path: Path) -> Deck:
    return Deck.model_validate_json(path.read_text())


@app.command()
def extract(
    config: Path,
    out: Annotated[Path, typer.Option(help="Where to write the ship model JSON.")],
) -> None:
    """Read a deck config and its PDF into a ship model."""
    deck, report = build_deck(config, get_llm())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(deck.model_dump_json(indent=1))
    typer.echo(f"{deck.name}: {len(deck.spaces)} spaces, {len(deck.doors)} doors, "
               f"{len(deck.unresolved_arcs_mm)} door arcs left for review")
    typer.echo(f"Scale: {deck.mm_per_pt:.3f} mm/pt. {deck.calibration_note}")
    if report.reviewed:
        typer.echo(f"OCR alone against reviewed labels: names {report.ocr_name_correct}/{report.reviewed}, "
                   f"compartment numbers {report.ocr_compartment_correct}/{report.reviewed}. Reviewed labels are used.")
    typer.echo(f"Wrote {out}")


@app.command()
def check(
    deck_json: Path,
    rules: Annotated[Path, typer.Option(help="Rule folder or file.")] = DEFAULT_RULES,
    scope: Annotated[Optional[str], typer.Option(help="Only this rule scope: escape or accessibility.")] = None,
    json_out: Annotated[Optional[Path], typer.Option(help="Also write findings as JSON.")] = None,
    overlay: Annotated[Optional[Path], typer.Option(help="Write an annotated PNG of the drawing.")] = None,
    explain: Annotated[bool, typer.Option(help="Add AI notes to findings. Verdicts do not change.")] = False,
) -> None:
    """Run the rules on a ship model."""
    deck = _load(deck_json)
    findings = run_checks(deck, load_rules(rules, scope))
    if explain:
        llm = get_llm()
        if llm is None:
            typer.echo("No LLM configured, so no notes were added.", err=True)
        else:
            add_explanations(findings, llm)
    typer.echo(findings_table(findings))
    if json_out:
        json_out.write_text(findings_json(findings, deck))
    if overlay:
        annotate(RAW / deck.source_pdf, deck, findings, png_out=overlay)
        typer.echo(f"Wrote {overlay}")


@app.command()
def inject(
    deck_json: Path,
    defect: Annotated[str, typer.Option(help="narrow_corridor, flip_door_swing, remove_exits, shrink_door, lengthen_dead_end or add_cabins.")],
    out: Annotated[Path, typer.Option(help="Where to write the changed ship model.")],
    id: Annotated[Optional[str], typer.Option(help="Space or door id.")] = None,
    ids: Annotated[Optional[str], typer.Option(help="Comma-separated door ids, for remove_exits.")] = None,
    to_mm: Annotated[Optional[float], typer.Option(help="New clear width in mm.")] = None,
    spur_mm: Annotated[Optional[float], typer.Option(help="Dead-end spur length in mm.")] = None,
    count: Annotated[Optional[int], typer.Option(help="Number of cabins.")] = None,
) -> None:
    """Inject a known defect into a ship model."""
    arguments = {"id": id, "to_mm": to_mm, "spur_mm": spur_mm, "count": count,
                 "ids": ids.split(",") if ids else None}
    changed = apply_defect(_load(deck_json), defect, {k: v for k, v in arguments.items() if v is not None})
    out.write_text(changed.model_dump_json(indent=1))
    typer.echo(f"Injected {changed.injected[-1]}. Wrote {out}")


@app.command()
def impact(
    deck_json: Path,
    add_cabins: Annotated[int, typer.Option(help="Number of cabins to add.")] = 6,
    berths_each: Annotated[int, typer.Option(help="Berths per added cabin.")] = 2,
    near: Annotated[Optional[str], typer.Option(help="Space id the cabins are near.")] = None,
) -> None:
    """Change impact: what adding cabins means, and who to notify."""
    deck = _load(deck_json)
    result = cabin_impact(deck, load_rules(DEFAULT_RULES), load_impact_map(DEFAULT_MAP), add_cabins, berths_each, near)
    typer.echo(f"Adding {result.count} cabins: {result.persons_added} more persons, {result.persons_total} in total.\n")
    typer.echo("Escape checks, re-run:")
    if result.newly_failing:
        for f in result.newly_failing:
            typer.echo(f"  NEW FAIL {f.rule_id} {f.subject_name}: {f.why}")
    else:
        typer.echo("  No new FAIL.")
    for f in result.findings:
        if f.rule_id == "ESC-STAIR-CAPACITY":
            typer.echo(f"  {f.verdict.value} {f.subject_name}: {f.why}")
    typer.echo("\nRules that now matter:")
    for rule in result.rules_that_apply:
        typer.echo(f"  {rule['ref']}: {rule['why']}")
    typer.echo("\nNotify (reminders only, nothing is calculated for these systems):")
    for person in result.notify:
        typer.echo(f"  {person['discipline']}: {person['why']}")


@app.command(name="eval")
def run_eval(
    deck_json: Path,
    defects: Annotated[Path, typer.Option(help="YAML file of defects and controls.")],
    rules: Annotated[Path, typer.Option(help="Rule folder or file.")] = DEFAULT_RULES,
) -> None:
    """Accuracy report: baseline, injected defects and false-alarm controls."""
    typer.echo(eval_table(evaluate(_load(deck_json), load_rules(rules), load_cases(defects))))


@app.command(name="analyze")
def analyze_file(
    file: Path,
    page: Annotated[int, typer.Option(help="Page index, for a PDF.")] = 0,
    mm_per_unit: Annotated[Optional[float], typer.Option(help="Scale: mm per PDF point, or per image pixel. Without it nothing is measured.")] = None,
    region: Annotated[Optional[str], typer.Option(help="Plan area x0,y0,x1,y1. Defaults to the whole sheet.")] = None,
    no_ai: Annotated[bool, typer.Option(help="Use geometry and OCR only.")] = False,
    json_out: Annotated[Optional[Path], typer.Option(help="Write the result as JSON.")] = None,
    image_out: Annotated[Optional[Path], typer.Option(help="Write the numbered drawing as an image.")] = None,
) -> None:
    """Analyse a new drawing: find spaces, name them and list what to check."""
    import json

    import cv2

    from keel.analyze import analysis_json, analysis_text, analyze

    box = tuple(float(v) for v in region.split(",")) if region else None
    result = analyze(file, None if no_ai else get_llm(), page, box, mm_per_unit)
    typer.echo(analysis_text(result))
    if json_out:
        json_out.write_text(json.dumps(analysis_json(result), indent=1))
    if image_out:
        cv2.imwrite(str(image_out), result.annotated)
        typer.echo(f"Wrote {image_out}")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Start the web viewer."""
    import uvicorn

    uvicorn.run("api.main:app", host=host, port=port)


if __name__ == "__main__":
    app()
