"""Accuracy evaluation: baseline, injected defects, and controls that must not alarm."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from keel.checks import run_checks
from keel.inject import apply_defect
from keel.model import Deck
from keel.rules import Rule
from keel.verdict import Finding, Verdict


@dataclass
class CaseResult:
    name: str
    kind: str  # defect | control
    expected: str
    passed: bool
    detail: str
    measured_mm: float | None = None
    target_mm: float | None = None
    new_fails: list[str] = field(default_factory=list)


@dataclass
class EvalReport:
    baseline_fail: int
    baseline_review: int
    baseline_pass: int
    cases: list[CaseResult]

    @property
    def defects(self) -> list[CaseResult]:
        return [c for c in self.cases if c.kind == "defect"]

    @property
    def controls(self) -> list[CaseResult]:
        return [c for c in self.cases if c.kind == "control"]

    @property
    def found(self) -> int:
        return sum(c.passed for c in self.defects)

    @property
    def false_alarms(self) -> int:
        return self.baseline_fail + sum(not c.passed for c in self.controls)


def _key(finding: Finding) -> tuple[str, str]:
    return (finding.rule_id, finding.subject_id)


def _matching(findings: list[Finding], rule_id: str, subject: str) -> Finding | None:
    for finding in findings:
        if _key(finding) == (rule_id, subject):
            return finding
    return None


def evaluate(deck: Deck, rules: list[Rule], cases: list[dict]) -> EvalReport:
    baseline = run_checks(deck, rules)
    baseline_fails = {_key(f) for f in baseline if f.verdict == Verdict.FAIL}
    results = []
    for case in cases:
        changed = apply_defect(deck, case["defect"], case.get("args", {}))
        findings = run_checks(changed, rules)
        new_fails = sorted(f"{r} on {s}" for r, s in {_key(f) for f in findings if f.verdict == Verdict.FAIL} - baseline_fails)
        target = _matching(findings, case["rule"], case["subject"])
        wanted = Verdict(case["expect"])
        got = target.verdict if target else None
        passed = got == wanted
        kind = case.get("kind", "defect")
        if kind == "control":
            # A control must also raise no alarm anywhere else.
            passed = passed and not new_fails
        results.append(
            CaseResult(
                name=case["name"],
                kind=kind,
                expected=f"{case['rule']} {wanted.value}",
                passed=passed,
                detail=(got.value if got else "no finding"),
                measured_mm=target.measured_mm if target else None,
                target_mm=case.get("target_mm"),
                new_fails=new_fails,
            )
        )
    verdicts = [f.verdict for f in baseline]
    return EvalReport(
        baseline_fail=verdicts.count(Verdict.FAIL),
        baseline_review=verdicts.count(Verdict.NEEDS_REVIEW),
        baseline_pass=verdicts.count(Verdict.PASS),
        cases=results,
    )


def load_cases(path: str | Path) -> list[dict]:
    return yaml.safe_load(Path(path).read_text())
