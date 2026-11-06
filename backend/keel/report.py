"""Outputs: terminal table, JSON and an annotated drawing. No verdicts are decided here."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pymupdf

from keel.evaluate import EvalReport
from keel.model import Deck
from keel.verdict import Finding, Verdict

COLORS = {
    Verdict.FAIL: (0.86, 0.1, 0.1),
    Verdict.NEEDS_REVIEW: (0.95, 0.6, 0.0),
    Verdict.PASS: (0.1, 0.6, 0.25),
}
ORDER = {Verdict.FAIL: 0, Verdict.NEEDS_REVIEW: 1, Verdict.PASS: 2}


def sort_findings(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (ORDER[f.verdict], f.rule_id, f.subject_id))


def summary_line(findings: list[Finding]) -> str:
    counts = Counter(f.verdict for f in findings)
    return (
        f"FAIL {counts[Verdict.FAIL]}   NEEDS_REVIEW {counts[Verdict.NEEDS_REVIEW]}   "
        f"PASS {counts[Verdict.PASS]}"
    )


def findings_table(findings: list[Finding]) -> str:
    lines = [summary_line(findings), ""]
    for f in sort_findings(findings):
        lines.append(f"[{f.verdict.value}] {f.rule_id}  {f.subject_name} ({f.subject_id})")
        lines.append(f"    {f.why}")
        if f.measured_mm is not None:
            lines.append(
                f"    measured {f.measured_display} | required {f.operator} {f.required_display} "
                f"| tolerance {f.tolerance_mm:.0f} mm | value {f.value_status}"
            )
        else:
            lines.append(f"    value {f.value_status}")
        lines.append(
            f"    evidence {f.source_pdf} page index {f.page_index} at "
            f"({f.location_pt[0]:.1f}, {f.location_pt[1]:.1f}) pt | source: {f.source}"
        )
        for assumption in f.assumptions:
            lines.append(f"    assumes: {assumption}")
        if f.explanation:
            lines.append(f"    AI note: {f.explanation}")
    return "\n".join(lines)


def findings_json(findings: list[Finding], deck: Deck) -> str:
    return json.dumps(
        {
            "deck": deck.name,
            "source_pdf": deck.source_pdf,
            "page_index": deck.page_index,
            "calibration": deck.calibration_note,
            "injected": deck.injected,
            "unresolved_door_arcs": len(deck.unresolved_arcs_mm),
            "findings": [f.model_dump(mode="json") for f in sort_findings(findings)],
        },
        indent=2,
    )


def eval_table(report: EvalReport) -> str:
    lines = [
        "Baseline (original drawing): "
        f"FAIL {report.baseline_fail}, NEEDS_REVIEW {report.baseline_review}, PASS {report.baseline_pass}",
        f"Injected defects found: {report.found} of {len(report.defects)}",
        f"False alarms: {report.false_alarms} (baseline FAILs plus controls that alarmed)",
        "",
    ]
    for title, cases in (("Defects", report.defects), ("Controls", report.controls)):
        lines.append(title)
        for c in cases:
            mark = "ok  " if c.passed else "MISS"
            measured = f" measured {c.measured_mm:.0f} mm" if c.measured_mm is not None else ""
            target = f" (injected {c.target_mm:.0f} mm)" if c.target_mm is not None else ""
            lines.append(f"  {mark} {c.name}: expected {c.expected}, got {c.detail}.{measured}{target}")
            others = [n for n in c.new_fails if not n.startswith(c.expected.split()[0])]
            if others:
                lines.append(f"       also failed: {', '.join(others)}")
        lines.append("")
    return "\n".join(lines).rstrip()


def annotate(
    pdf_path: str | Path,
    deck: Deck,
    findings: list[Finding],
    pdf_out: str | Path | None = None,
    png_out: str | Path | None = None,
    clip_pt: tuple[float, float, float, float] | None = None,
    dpi: int = 200,
    include_pass: bool = False,
) -> None:
    """Draw findings on the original drawing, so engineers see them in place."""
    with pymupdf.open(pdf_path) as document:
        page = document[deck.page_index]
        to_page = ~page.rotation_matrix

        def transform(point):
            return pymupdf.Point(point) * to_page

        shape = page.new_shape()
        for finding in reversed(sort_findings(findings)):
            if finding.verdict == Verdict.PASS and not include_pass:
                continue
            color = COLORS[finding.verdict]
            if finding.overlay_polygon_pt:
                shape.draw_polyline([transform(p) for p in finding.overlay_polygon_pt])
                shape.finish(color=color, fill=color, fill_opacity=0.12, width=0.5, closePath=True)
            for line in finding.overlay_lines_pt:
                shape.draw_polyline([transform(p) for p in line])
                shape.finish(color=color, width=1.6)
            center = transform(finding.location_pt)
            shape.draw_circle(center, 4.5)
            shape.finish(color=color, width=1.1)
        shape.commit()
        if pdf_out:
            document.save(pdf_out)
        if png_out:
            clip = pymupdf.Rect(*clip_pt) if clip_pt else None
            page.get_pixmap(dpi=dpi, clip=clip).save(png_out)
