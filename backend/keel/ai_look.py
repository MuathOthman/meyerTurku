"""AI looks where the code is blind.

When a check cannot be measured, usually because no doors were found, the vision model is shown
that space with its outline in red and asked one plain question for that rule. Its answer is
evidence for the engineer, never a verdict: the finding stays NEEDS_REVIEW until someone
confirms it. The model is never asked for a measurement, because it cannot read millimetres
reliably from pixels.
"""
from __future__ import annotations

import io
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw

from keel.llm import LLM, LLMError
from keel.verdict import Finding, Verdict

log = logging.getLogger(__name__)

MAX_SIDE_PX = 1400
MARGIN_PT = 60.0  # About 2.6 m at 1:125, so the doors around the space are in view.

# One question per check. The rule's own numbers are named, but the model is asked what it
# sees, not to measure.
QUESTIONS = {
    "dead_end": (
        "Follow the corridor outlined in red. Find where it leads to a stair, the open deck or "
        "another corridor. Does any part of it lead nowhere, so a person walking in would have "
        "to turn back, for more than about 7 m?",
        "looks_ok means no dead end longer than about 7 m.",
    ),
    "two_means": (
        "Count the separate ways out of the space outlined in red: doors or openings that lead "
        "towards a stair, a ladder or the open deck by different routes. Two doors into the "
        "same room count once.",
        "looks_ok means at least two separate ways out.",
    ),
    "corridor_width": (
        "Look at the corridor outlined in red. Is anything drawn inside it that narrows the "
        "walking route, such as furniture, equipment, steps or a column?",
        "looks_ok means nothing narrows the route. Do not estimate the width in millimetres.",
    ),
    "machinery_other_escape": (
        "Count the ways out of the machinery space outlined in red: doors, stairs or ladders "
        "leading out of it. If there is only one, say whether every part of the space is close "
        "to it, within about 5 m.",
        "looks_ok means two ways out, or one way out that every part of the space is close to.",
    ),
    "machinery_a_escape": (
        "Count the steel ladders, stairs and doors leading out of the engine room outlined in "
        "red, and say whether two of them are far apart from each other.",
        "looks_ok means two ways out, widely separated.",
    ),
    "door_swing": (
        "Find doors leading from corridors towards stairs or the open deck. A door swing is drawn "
        "as an arc. Does any such door open against the way people escape, that is back into "
        "the corridor they are leaving? Cabin doors are allowed to open into the cabin.",
        "looks_ok means every such door opens the way people escape.",
    ),
}

WHOLE_DECK = {"door_swing"}

SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "enum": ["looks_ok", "looks_wrong", "unsure"]},
        "seen": {"type": "string"},
        "count": {"type": "integer"},
    },
    "required": ["answer", "seen", "count"],
}

PROMPT = """This is part of a ship general arrangement drawing, a deck plan at about 1:125.
{target}

Question: {question}
{meaning}

Answer with:
- answer: looks_ok, looks_wrong, or unsure when the drawing does not show it clearly.
- seen: one or two plain sentences saying what you see that led to your answer, naming where on the image.
- count: the number of ways out or doors you counted, or -1 if you did not count anything.
Do not give measurements. Do not say the design is compliant or approved. An engineer decides."""


def _render(path: Path, page: int, outline: list[tuple[float, float]], clip: pymupdf.Rect) -> bytes:
    with pymupdf.open(path) as document:
        sheet = document[page]
        clip = clip & sheet.rect
        zoom = min(MAX_SIDE_PX / max(clip.width, clip.height), 6.0)
        pixmap = sheet.get_pixmap(clip=clip, matrix=pymupdf.Matrix(zoom, zoom))
    image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")
    if len(outline) >= 3:
        draw = ImageDraw.Draw(image)
        points = [((x - clip.x0) * zoom, (y - clip.y0) * zoom) for x, y in outline]
        draw.line(points + points[:1], fill=(220, 30, 30), width=4)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def _view(path: Path, page: int, finding: Finding, region: tuple | None) -> bytes:
    """The space with a margin, or the whole deck when the rule found nothing to point at."""
    outline = finding.overlay_polygon_pt
    if outline and finding.subject_id != "deck":
        xs, ys = zip(*outline)
        clip = pymupdf.Rect(min(xs) - MARGIN_PT, min(ys) - MARGIN_PT, max(xs) + MARGIN_PT, max(ys) + MARGIN_PT)
        return _render(path, page, outline, clip)
    clip = pymupdf.Rect(*region) if region else pymupdf.Rect(0, 0, 1e6, 1e6)
    return _render(path, page, [], clip)


def look(
    path: str | Path,
    page: int,
    findings: list[Finding],
    check_of: dict[str, str],
    llm: LLM,
    region: tuple | None = None,
    on_progress: Callable[[int, int], None] = lambda done, total: None,
) -> int:
    """Ask the AI about each finding Keel could not measure. Changes them in place.

    check_of maps a rule id to its check. Returns how many findings the AI looked at.
    """
    path = Path(path)
    if path.suffix.lower() != ".pdf":
        return 0
    # A whole-deck question about corridors on a deck with none gets no useful answer. Door
    # swing is the one rule worth asking about across a whole deck.
    jobs = [
        f for f in findings
        if check_of.get(f.rule_id) in QUESTIONS
        and (f.subject_id != "deck" or check_of[f.rule_id] in WHOLE_DECK or "Keel found" in f.why)
    ]

    def ask(finding: Finding) -> dict:
        question, meaning = QUESTIONS[check_of[finding.rule_id]]
        target = (
            "The whole deck plan is shown, with no red outline: consider every corridor on it." if finding.subject_id == "deck"
            else f"The space outlined in red is: {finding.subject_name}."
        )
        image = _view(path, page, finding, region)
        prompt = PROMPT.format(target=target, question=question, meaning=meaning)
        return llm.complete_json(prompt, SCHEMA, images=[image])

    looked = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [(f, pool.submit(ask, f)) for f in jobs]
        on_progress(0, len(futures))
        for done, (finding, future) in enumerate(futures, start=1):
            try:
                answer = future.result()
            except (LLMError, RuntimeError, ValueError) as error:
                log.warning("AI could not look at %s: %s", finding.rule_id, error)
                on_progress(done, len(futures))
                continue
            seen = str(answer.get("seen", "")).strip()
            result = answer.get("answer") if answer.get("answer") in ("looks_ok", "looks_wrong", "unsure") else "unsure"
            if not seen:
                continue
            finding.assumptions = [f"Keel could not measure this: {finding.why}", *finding.assumptions]
            finding.why = f"AI looked at the drawing: {seen}"
            finding.verdict = Verdict.NEEDS_REVIEW  # AI evidence never passes or fails anything.
            finding.ai_look = {"answer": result, "seen": seen, "count": int(answer.get("count", -1))}
            looked += 1
            on_progress(done, len(futures))
    return looked
