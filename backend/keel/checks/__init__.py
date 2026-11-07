"""Deterministic checks. One function per check type: (deck, rule) -> list of Finding."""
from __future__ import annotations

from collections.abc import Callable

from keel.checks.accessibility import accessible_door, accessible_route, accessible_turning
from keel.checks.escape import (
    corridor_width,
    dead_end,
    door_swing,
    escape_door_width,
    galley_lobby,
    sole_stair,
    stair_capacity,
    stair_width,
    two_means,
)
from keel.checks.common import base_finding
from keel.model import Deck
from keel.rules import Rule
from keel.verdict import Finding, Verdict

CHECKS: dict[str, Callable[[Deck, Rule], list[Finding]]] = {
    "corridor_width": corridor_width,
    "stair_width": stair_width,
    "stair_capacity": stair_capacity,
    "escape_door_width": escape_door_width,
    "door_swing": door_swing,
    "two_means": two_means,
    "dead_end": dead_end,
    "sole_stair": sole_stair,
    "galley_lobby": galley_lobby,
    "accessible_door": accessible_door,
    "accessible_route": accessible_route,
    "accessible_turning": accessible_turning,
}


def run_checks(deck: Deck, rules: list[Rule]) -> list[Finding]:
    """Run every rule. A rule naming an unknown check is an error, never silently skipped."""
    findings: list[Finding] = []
    for rule in rules:
        if rule.check not in CHECKS:
            raise KeyError(f"rule {rule.id} names unknown check {rule.check!r}")
        produced = CHECKS[rule.check](deck, rule)
        if not produced and not _optional_when_empty(rule):
            produced = [_not_applied(deck, rule)]
        findings.extend(produced)
    return findings


def _optional_when_empty(rule: Rule) -> bool:
    """ADA rules need spaces marked accessible, and many decks have no galley. Neither is a gap."""
    return bool({"accessible", "galley"} & set(rule.applies_to))


def _not_applied(deck: Deck, rule: Rule) -> Finding:
    """An empty report must not read as a clean report."""
    return base_finding(
        deck, rule, Verdict.NEEDS_REVIEW, "deck", deck.name, (0.0, 0.0),
        f"This rule could not be applied: nothing of type {', '.join(rule.applies_to)} was found "
        "on this deck. It has not been checked, so an engineer should confirm the room labels.",
    )
