"""Plain-language notes on findings, from the LLM. Optional and advisory.

The LLM receives finished findings and may only rephrase them. Numbers and verdicts are not
read back from its answer, and notes containing numbers not in the finding are dropped.
"""
from __future__ import annotations

import logging
import re

from keel.llm import LLM, LLMError
from keel.verdict import Finding

log = logging.getLogger(__name__)

SCHEMA = {
    "type": "object",
    "properties": {
        "notes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"index": {"type": "integer"}, "note": {"type": "string"}},
                "required": ["index", "note"],
            },
        }
    },
    "required": ["notes"],
}


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text))


def note_is_safe(note: str, finding: Finding) -> bool:
    """Every number in the note must already appear in the finding's evidence."""
    allowed = _numbers(
        " ".join(
            [finding.why, finding.source, finding.rule_id, finding.subject_id, finding.subject_name,
             finding.interpretation_note, *finding.assumptions]
        )
    )
    return _numbers(note) <= allowed


def add_explanations(findings: list[Finding], llm: LLM) -> list[Finding]:
    """Add a short note to FAIL and NEEDS_REVIEW findings. PASS findings need none."""
    targets = [f for f in findings if f.verdict.value != "PASS"]
    if not targets:
        return findings
    described = "\n".join(
        f"{i}. {f.verdict.value} {f.rule_title}. {f.why} How it is applied: {f.interpretation_note}"
        for i, f in enumerate(targets)
    )
    prompt = (
        "You help a ship design engineer read compliance findings. For each finding write one "
        "sentence saying what the engineer should look at and why it matters. Do not change "
        "any verdict. Use only the facts given: add no numbers, regulations or reasons of your own, "
        "and keep the stated reason for the verdict. Do not say the design is compliant or "
        f"certified.\n{described}"
    )
    try:
        answer = llm.complete_json(prompt, SCHEMA)
    except LLMError as error:
        log.warning("AI notes were not added: %s", error)
        return findings
    for item in answer.get("notes", []):
        index = item.get("index")
        if isinstance(index, int) and 0 <= index < len(targets):
            note = str(item.get("note", "")).strip()
            if note and note_is_safe(note, targets[index]):
                targets[index].explanation = note
            elif note:
                log.warning("Dropped an AI note with numbers not in the evidence: %s", note)
    return findings
