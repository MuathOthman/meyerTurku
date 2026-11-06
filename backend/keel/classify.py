"""Room name -> category. The only fuzzy step in Keel, and it is contained.

A keyword table handles the vocabulary we have reviewed. Other names may go to the LLM, but
an LLM answer is capped below the trust threshold, so it can only lead to NEEDS_REVIEW.
AI alone can never cause a FAIL. An engineer's review is what raises confidence.
"""
from __future__ import annotations

import logging

from keel.llm import LLM, LLMError
from keel.model import Category

log = logging.getLogger(__name__)

KEYWORD_CONFIDENCE = 0.95
LLM_CONFIDENCE_CAP = 0.75

# Checked in order, so specific names come before general ones.
KEYWORDS: list[tuple[str, Category]] = [
    ("BOARDING", Category.OPEN_DECK),
    ("EMERGENCY CONTROL", Category.CONTROL),
    ("GALLEY", Category.GALLEY),
    ("SCULLERY", Category.GALLEY),
    ("STORES", Category.STORES),
    ("MESS", Category.PUBLIC),
    ("LOUNGE", Category.PUBLIC),
    ("W/C", Category.SANITARY),
    ("LAB", Category.LAB),
    ("ER ACCESS", Category.STAIR),
    ("GARBAGE", Category.SERVICE),
    ("FAN ROOM", Category.MACHINERY),
    ("FIRE SUPPRESSION", Category.MACHINERY),
    ("PASSAGEWAY", Category.CORRIDOR),
    ("CORRIDOR", Category.CORRIDOR),
    ("LOCKER", Category.SERVICE),
    ("STAIR", Category.STAIR),
    ("HOSPITAL", Category.MEDICAL),
    ("HVAC", Category.MACHINERY),
    ("VENTILATION", Category.MACHINERY),
    ("UPTAKE", Category.MACHINERY),
    ("TRUNK", Category.MACHINERY),
    ("MOORING", Category.MACHINERY),
    ("DECK OPERATIONS", Category.SERVICE),
    ("LOCKER", Category.SERVICE),
    ("LKR", Category.SERVICE),
    ("LAUNDRY", Category.SERVICE),
    ("HAZ MAT", Category.SERVICE),
    ("ELECTRONICS", Category.CONTROL),
    ("SWBD", Category.MACHINERY),
    ("GENERATOR", Category.MACHINERY),
    ("FUEL TANK", Category.MACHINERY),
    ("CAPTAIN", Category.CABIN),
    ("MASTER", Category.CABIN),
    ("MATE", Category.CABIN),
    ("ENGINEER", Category.CABIN),
    ("3RD ENG", Category.CABIN),
    ("2ND ENG", Category.CABIN),
    ("CHIEF ENG", Category.CABIN),
    ("OFFICER", Category.CABIN),
    ("CABIN", Category.CABIN),
    ("STATEROOM", Category.CABIN),
    ("BRIDGE", Category.CONTROL),
    ("PILOTHOUSE", Category.CONTROL),
    ("WHEELHOUSE", Category.CONTROL),
    ("CHIEF SCIENCE", Category.CABIN),
    ("SCIENCE", Category.CABIN),
    ("CREW", Category.CABIN),
    ("MARINE TECH", Category.CABIN),
]


def classify_by_keyword(name: str) -> tuple[Category, float] | None:
    upper = name.upper()
    for keyword, category in KEYWORDS:
        if keyword in upper:
            return category, KEYWORD_CONFIDENCE
    return None


CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "rooms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "category": {"type": "string", "enum": [c.value for c in Category]},
                    "confidence": {"type": "number"},
                },
                "required": ["name", "category", "confidence"],
            },
        }
    },
    "required": ["rooms"],
}


def classify_with_llm(names: list[str], llm: LLM) -> dict[str, tuple[Category, float]]:
    """Ask the LLM about names the table does not know. Failures just leave them unknown."""
    if not names:
        return {}
    prompt = (
        "These are room labels from a ship general arrangement drawing, read by OCR, so they "
        "may have errors. Give each one a category. Use unknown when unsure, or when the text "
        f"is not a room name.\nLabels: {names}"
    )
    try:
        answer = llm.complete_json(prompt, CLASSIFY_SCHEMA)
    except LLMError as error:
        log.warning("Room classification by LLM failed, names stay unknown: %s", error)
        return {}
    result = {}
    for room in answer.get("rooms", []):
        try:
            category = Category(room["category"])
            confidence = min(float(room["confidence"]), LLM_CONFIDENCE_CAP)
        except (KeyError, TypeError, ValueError):
            continue
        result[room.get("name", "")] = (category, confidence)
    return result


def classify(names: list[str], llm: LLM | None) -> dict[str, tuple[Category, float]]:
    known = {name: found for name in names if (found := classify_by_keyword(name))}
    unknown = [name for name in names if name not in known]
    answers = classify_with_llm(unknown, llm) if llm else {}
    result = dict(known)
    for name in unknown:
        result[name] = answers.get(name, (Category.UNKNOWN, 0.0))
    return result
