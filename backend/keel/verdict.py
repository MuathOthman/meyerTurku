"""The verdict policy, the core of accuracy. No other module decides a verdict.

  FAIL          numeric rule, trusted inputs, and violated by more than the tolerance
  PASS          requirement met by more than the tolerance
  NEEDS_REVIEW  everything else: borderline, low confidence, or a judgment rule

A false alarm costs engineers' trust, so anything uncertain goes to a human.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

HIGH_CONFIDENCE = 0.8


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NEEDS_REVIEW = "NEEDS_REVIEW"


def margin_mm(measured_mm: float, required_mm: float, operator: str) -> float:
    """Positive when the requirement is met, whichever way the rule is written."""
    if operator == ">=":
        return measured_mm - required_mm
    if operator == "<=":
        return required_mm - measured_mm
    raise ValueError(f"unsupported operator {operator!r}")


def numeric_verdict(
    measured_mm: float,
    required_mm: float,
    operator: str,
    tolerance_mm: float,
    applicability_confidence: float = 1.0,
    classification_confidence: float = 1.0,
) -> Verdict:
    margin = margin_mm(measured_mm, required_mm, operator)
    trusted = (
        applicability_confidence >= HIGH_CONFIDENCE and classification_confidence >= HIGH_CONFIDENCE
    )
    if margin > tolerance_mm:
        # A clear pass stays a pass even when applicability is uncertain.
        return Verdict.PASS
    if margin < -tolerance_mm and trusted:
        return Verdict.FAIL
    return Verdict.NEEDS_REVIEW


def geometric_verdict(
    compliant: bool, applicability_confidence: float = 1.0, classification_confidence: float = 1.0
) -> Verdict:
    """For yes/no geometry, such as door swing or the number of escape routes."""
    if applicability_confidence < HIGH_CONFIDENCE or classification_confidence < HIGH_CONFIDENCE:
        return Verdict.NEEDS_REVIEW
    return Verdict.PASS if compliant else Verdict.FAIL


class Finding(BaseModel):
    """A verdict with all its evidence. Every field is deterministic except `explanation`."""

    rule_id: str
    rule_title: str
    source: str
    ref_url: str = ""
    value_status: str  # verified | assumed
    verdict: Verdict
    subject_id: str
    subject_name: str
    source_pdf: str
    page_index: int
    location_mm: tuple[float, float]
    location_pt: tuple[float, float]
    measured_mm: float | None = None
    measured_display: str = ""
    required_mm: float | None = None
    required_display: str = ""
    operator: str = ""
    tolerance_mm: float | None = None
    margin_mm: float | None = None
    why: str
    interpretation_note: str = ""
    assumptions: list[str] = Field(default_factory=list)
    overlay_lines_pt: list[list[tuple[float, float]]] = Field(default_factory=list)
    overlay_polygon_pt: list[tuple[float, float]] = Field(default_factory=list)
    explanation: str | None = None
    why_it_matters: str = ""
    fix: str = ""
