# Keel architecture

**AI reads, code measures, engineer decides.**

```
Vector PDF
  │  extract.py    lines, curves and fills, in displayed page coordinates
  ▼
calibrate.py       mm per point from the frame ruler, verified against the printed beam
  ▼
doors.py           swing arcs → doors (hinge, latch, swing side), or "unresolved"
rooms.py           floor = plan − walls − closed doors; a room is the free cell at its label
labels.py          OCR on a text-only image, leader lines trace each label to its room   ← AI reads
classify.py        room name → category; keyword table, then LLM capped below trust      ← AI reads
  ▼
model.py           neutral ship model in mm. Checks never see the PDF
graph.py           escape graph: spaces and doors
  ▼
checks/            pure functions, one per check type
verdict.py         the only place a verdict is decided
  ▼
report.py, api/    table, JSON, annotated drawing, web viewer
explain.py         optional AI notes. Cannot change anything, and numbers are checked
```

## Route for new drawings

`keel analyze` (`keel/analyze.py`) handles a drawing with no setup:

```
spaces.py    vector PDF: drawn walls, line weights detected automatically
raster.py    image: pixel segmentation with watershed at door gaps (rough)
labels.py    leader tracing plus OCR, then text printed in the room
vision model only for spaces still unnamed; names are capped below the trust threshold
config/applicability.yaml   fixed map from space type to what the engineer should check
checks/      run only with a given scale, and on the vector route
```

Tracing is the primary naming route because a vision model named neighbouring rooms when asked to
follow thin leader lines. See the README for scores.

## Findings from the real drawing that shaped the design

| The brief assumed | The drawing shows | What Keel does |
|---|---|---|
| Extractable text | No text layer on any of 12 pages | OCR on an image drawn only from the 0.18 pt text strokes, so walls cannot garble letters |
| Scale from the title block | It says 1/8"=1'-0", but the print is 0.488 of that | Measures the frame ruler, then verifies against the printed beam (0.024% apart). Refuses to run if they disagree |
| Labels inside rooms | Most sit outside, on leaders ending in a dot in the room | Traces leaders from the dot |
| Closed wall polygons for `polygonize` | Furniture, door hardware and leaders cross everything | Subtracts walls from the plan and takes the free cell at each label |
| Quarter-circle door arcs | Cabin door arcs are trimmed to about 52° | Finds a door from its perpendicular leaf and closed directions, and wall along the closed one |

## Verdict policy

`tolerance = length × scale error + extraction tolerance (one 0.36 pt stroke, 25 mm)`

- **FAIL**: violated by more than the tolerance, and applicability and classification are both trusted (at least 0.8)
- **PASS**: met by more than the tolerance
- **NEEDS_REVIEW**: everything else

Safeguards against false alarms:

- A room category from the LLM alone is capped at 0.75, so AI alone can never cause a FAIL.
- A door whose swing cannot be read goes to review.
- A rule with nothing to check reports that, so an empty report cannot read as clean.
- Side branches report their real width, but go to review, since the rule's application is a judgment.
- AI notes containing numbers that are not in the evidence are dropped.

## Measurement methods

| Check | Method |
|---|---|
| Corridor clear width | Binary search for the largest erosion that keeps exit doors connected. Obstacles under 110 mm are ignored |
| Stair width | Largest inscribed circle in the stair enclosure |
| Door clear width | Arc radius minus a 50 mm frame allowance. This is an assumption |
| Door swing | Which side of the closed door line the arc lies on |
| Two means | Different exits reachable through circulation spaces only, never through rooms |
| Dead end | Walking distance on a 100 mm grid from the route between exits, minus local width |
| Stair capacity | `(N1 + N2) × 10 mm`, IMO A.757(18) |

## Extending to other sources

Checks read only `Deck`. An OCX, IFC or Navisworks importer has to produce the same model. None is
built yet.
