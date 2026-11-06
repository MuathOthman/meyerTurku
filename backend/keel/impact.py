"""Change impact: "I add a cabin. What now matters, and who should know?"

Rule results are real re-runs of the checks. Notifications come from a dependency map and
are only reminders: there is no system data, so nothing about HVAC or water is calculated.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from keel.checks import run_checks
from keel.inject import add_cabins
from keel.model import Deck
from keel.rules import Rule
from keel.verdict import Finding, Verdict


@dataclass
class ImpactResult:
    count: int
    persons_added: int
    persons_total: int
    findings: list[Finding]
    newly_failing: list[Finding]
    rules_that_apply: list[dict]
    notify: list[dict]


def load_impact_map(path: str | Path) -> dict:
    return yaml.safe_load(Path(path).read_text())


def cabin_impact(
    deck: Deck,
    rules: list[Rule],
    impact_map: dict,
    count: int,
    berths_each: int = 2,
    near: str | None = None,
) -> ImpactResult:
    changed = add_cabins(deck, count, berths_each, near)
    escape_rules = [r for r in rules if r.scope == "escape"]
    before = {(f.rule_id, f.subject_id) for f in run_checks(deck, escape_rules) if f.verdict == Verdict.FAIL}
    findings = run_checks(changed, escape_rules)
    newly = [f for f in findings if f.verdict == Verdict.FAIL and (f.rule_id, f.subject_id) not in before]
    entry = impact_map["cabin"]
    return ImpactResult(
        count=count,
        persons_added=count * berths_each,
        persons_total=changed.total_berths + changed.persons_other_decks,
        findings=findings,
        newly_failing=newly,
        rules_that_apply=entry["rules"],
        notify=entry["notify"],
    )
