# Keel: compliance checking for ship drawings

**AI reads, code measures, engineer decides.**

Keel reads a general arrangement drawing, works out its rooms, doors and escape routes, and checks
them against a rule database. Every finding shows why: the measured value, the required value, the
tolerance, the rule source and the location on the drawing.

Built for the Meyer Turku challenge at Since AI Hackathon 2026. Demonstrated on the public
[Oregon State RCRV](https://ceoas.oregonstate.edu/regional-class-research-vessel-ship-design) research
vessel, 01 Level. RCRV is not a cruise ship, so the rules are applied for demonstration. Keel does
not certify compliance; an engineer decides.

## Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
scripts/get_data.sh
.venv/bin/keel extract data/decks/rcrv_01_level.yaml --out data/processed/deck01.json
.venv/bin/keel check data/processed/deck01.json
.venv/bin/keel eval data/processed/deck01.json --defects data/decks/rcrv_01_level_eval.yaml
.venv/bin/keel serve        # API and web app on http://127.0.0.1:8000
```

The web app lives in `../frontend`. See the [root README](../README.md) to run both together.

Inject a defect and check again:

```bash
.venv/bin/keel inject data/processed/deck01.json --defect flip_door_swing --id D-21 --out /tmp/flipped.json
.venv/bin/keel check /tmp/flipped.json --overlay /tmp/flipped.png
```

See what adding cabins changes:

```bash
.venv/bin/keel impact data/processed/deck01.json --add-cabins 40
```

## Results on RCRV 01 Level

| Measure | Result |
|---|---|
| Scale check: beam measured against printed | 12,500 mm against 12,497 mm (0.024%) |
| Extracted | 45 spaces, 42 doors, 6 door arcs left for review |
| Original drawing | 0 FAIL, 2 NEEDS_REVIEW, 14 PASS |
| Injected defects found | 11 of 11 |
| False alarms | 0, on the baseline and 8 controls |
| Injected widths measured back | Within about 1 mm |
| Tests | 170 backend and 14 frontend, passing |

**The first NEEDS_REVIEW is a real observation.** The side branch to the Hospital and a crew cabin is
846 mm wide at the gap beside the centerboard trunk, against an assumed 900 mm. The main route between
exits is 1,049 mm at its narrowest. Whether the rule applies to that branch is an engineer's call.

**The second NEEDS_REVIEW** is the DNV lobby rule. The passageway between the Laundry and the stair
is large enough, at 1,049 mm and 23.8 m², but Keel cannot see the fire hose station the rule also
requires, or tell whether this corridor counts as the lobby.

### What these numbers do and do not prove

- We wrote the defects and controls ourselves, and they are injected into the ship model. They test
  the checks and the verdict policy. They do not test whether door and room extraction is right.
- "Measured back within 1 mm" shows the geometry code is consistent. It is not an independent
  accuracy check. That is the ruler comparison below.
- Doors and rooms were checked by eye on overlays of this one deck. There is no measured extraction
  accuracy yet, and other decks have not been tried.
- Labels used in these checks are hand-read from the drawing, standing in for an engineer's
  confirmation. See "Accuracy on unreviewed drawings" below for how well Keel names rooms alone.
- Three rule values are assumed or unsourced. See [docs/RULES.md](docs/RULES.md).

### Ruler check

Compare these in a PDF viewer or Autodesk Viewer. To convert in a PDF viewer, the frame ruler spacing is
8.783 pt per 2 ft frame on this print, which is 69.41 mm per pt.

| Item | Keel | Page location |
|---|---|---|
| Passageway width, forward section | 1,160 mm | x 670, y 167 to 184 pt |
| Passageway width, aft section | 1,049 mm | near x 554, y 175 pt |
| Side branch gap | 846 mm | near x 599, y 190 pt |
| Moulded beam | 12,500 mm | y 104.49 to 284.58 pt |

Keel measures clear width from the ink edge of each wall line, so a viewer snapping to line centres
reads about 25 mm more.

## Analysing a new drawing

```bash
.venv/bin/keel analyze my_plan.pdf --page 8 --mm-per-unit 69.41 --json-out out.json --image-out numbered.png
.venv/bin/keel analyze scan.png --no-ai
```

Or use the upload page at `/app/new` in the web app.

1. **Find spaces, deterministic.** Vector PDFs use the drawn walls, with wall line weights detected
   automatically. Images use pixel segmentation, which is much less accurate.
2. **Name spaces.** Follow each leader line from the dot in the room to its printed label, and read
   the label with OCR. Otherwise use text printed in the room. A vision model is used only for what
   remains. Names go to an engineer, and cannot cause a FAIL until confirmed.
3. **List what to check, fixed map.** `config/applicability.yaml` lists the rules for each type of
   space, and marks any reference we have not confirmed in the source.
4. **Measure, deterministic.** Only for vector PDFs with a given scale. Results can be PASS or
   NEEDS_REVIEW only. Without a scale, nothing is measured.

### Accuracy on unreviewed drawings

Scored against answer keys read by eye, each written before the first run on that sheet.

**Clean tests, run before the code was changed for that sheet:**

| Sheet | Method | Space found | Name correct |
|---|---|---|---|
| 02 Level | AI vision only | 16 of 21 | 6 of 21 |
| 03 Level | Tracing and OCR, no AI | 5 of 8 | 1 of 8 |

**Final code. The vector rows are optimistic, because all three sheets were used to develop it:**

| Input | Sheet | Space found | Name correct | Type correct |
|---|---|---|---|---|
| PDF + ChatGPT | 02 Level | 19 of 21 | 17 of 21 | 18 of 21 |
| PDF + ChatGPT | Main Deck | 20 of 21 | 14 of 21 | 14 of 21 |
| PDF + ChatGPT | 03 Level | 5 of 8 | 3 of 8 | 4 of 8 |
| **PDF total** | | **44 of 50** | **34 of 50** | **36 of 50** |
| Image + ChatGPT | 02 Level | 12 of 21 | 9 of 21 | 10 of 21 |
| Image + ChatGPT | Main Deck | 17 of 21 | 11 of 21 | 12 of 21 |
| **Image total** | | **29 of 42** | **20 of 42** | **22 of 42** |

**Read this as: a useful first draft for an engineer to correct, not a reliable result.** About a third
of room names are wrong on PDFs and about half on images. A wrong name gives a wrong checklist. All
sheets come from one drawing set and one CAD standard, and no other shipyard's drawing has been tried.

What we learned: a vision model cannot reliably follow thin leader lines, naming neighbouring rooms
instead (6 of 21). Tracing the lines in the vector data is far better (17 of 21 on the same sheet).

## Limitations

- The checked results above are one deck of one vessel. Other sheets are named as shown in the table.
- 2D only. Image input is a rough first pass, and it cannot follow leader lines or measure doors.
- Areas are of the free floor cell, so furniture attached to walls can reduce them.
- Door clear width is the arc radius minus an assumed 50 mm.
- Stair width does not deduct handrails, and persons on other decks is a config input.
- "Add cabins" changes the persons count; it does not redraw the layout.
- Discipline notifications are reminders. Keel has no HVAC or water data.

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): how it works and the verdict policy
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md): running it, including with a local model
- [docs/RULES.md](docs/RULES.md): rule sources and what is verified
