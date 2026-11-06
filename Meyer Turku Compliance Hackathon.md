# Keel: compliance checker for ship drawings
Since AI Hackathon 2026, Turku · Meyer Turku challenge "Automated Class & Regulatory Compliance Checking"
Event: Fri 6 Nov 16:00 → Sun 8 Nov 17:00. Peer voting Sun 10:00–12:00, so **submit before Sun ~09:00** (check exact deadline in sinceai.app).

> This file is the full handoff. Read it fully before writing code. Everything here was decided after the Meyer kickoff meeting on Fri 6 Nov.

---

## 0. Instructions for Claude Code (working rules)

1. **AI reads, code measures, engineer decides.** LLMs may label things (room types, abbreviations) and write explanations. LLMs must NEVER produce a measurement or a pass/fail decision. All numbers come from deterministic geometry code.
2. **Every finding must carry evidence:** source drawing + page + coordinates, the measured value, the required value, the rule id + source reference, and the tolerance used.
3. **Units:** store everything internally in **millimetres (SI)**. The RCRV drawings are American and may be in feet/inches. Convert on input, display both.
4. **Verdicts are only PASS / FAIL / NEEDS_REVIEW.** See section 6 for the exact policy. Zero false positives matter more than catching everything.
5. **No Blender** (Meyer explicitly said so). No 3D work for now (decision in section 3).
6. Keep the core a **Python library + CLI** first. The web UI is a thin layer on top.
7. Write a pytest for every geometry function and every rule check. Accuracy is the #1 judging criterion.
8. Do not paste long copyrighted rule texts into the repo. Store our own short summary + reference + link.
9. Prefer simple, readable code over clever code. We have ~36 hours.

---

## 1. The challenge in plain words

Meyer Turku builds cruise ships (Icon class etc.). Every design must comply with many overlapping rules: SOLAS, MARPOL, COLREG, Load Line, Tonnage, classification society rules (DNV, Lloyd's), PVAG and ADA (US accessibility). Today engineers check this **manually**, it needs **senior people**, and mistakes are found late. Their example: a door opening the wrong way costs ~1 hour to fix in design but is really expensive in production.

**Guiding question (from brief):** How could designs be checked against class rules (e.g. DNV), SOLAS and regulations early, before conflicts propagate downstream?

**Users:** indoor design engineers in basic design and detailed design. Use case: "click a button and it tells me this pathway is too narrow."

---

## 2. What Meyer said in the kickoff (requirements checklist)

Sources: kickoff transcript (42 min), challenge presentation (10 slides), challenge brief PDF.

| # | Requirement | Their words / source |
|---|---|---|
| R1 | Check the **ship design itself** (documents, drawings and/or 3D models) | Brief section 06, slide 8 |
| R2 | **Accuracy:** correctly identify compliant vs non-compliant, minimise misleading findings, ideally **no false positives** | Slide 8, transcript 12:44–13:19 |
| R3 | Their example design is expected to be compliant. **Inject errors** yourself to test | Transcript 13:00 |
| R4 | Show one **compliant** and one **non-compliant** case | Transcript 13:31 |
| R5 | Prove a measurement against the **viewer's own measuring tool** ("tool says 3 m, model says 3 m") | Transcript 13:40 |
| R6 | **Design interpretation:** understand drawings, clearly highlight **why** something is not compliant | Slide 8 |
| R7 | **Solid technical foundation > polished UI.** CLI is acceptable. Plugins acceptable | Slide 8, transcript 14:03–14:30 |
| R8 | Not locked to any CAD. Open-source CAD kernels fine. **No Blender** | Transcript 14:36–14:57 |
| R9 | **Rules are not the core.** A small rule set in a database is fine. Made-up parameters OK, real ones better | Transcript 15:55–17:21 |
| R10 | Class rules = numbers/formulas. Statutory (SOLAS) = vague, needs interpretation, "read between the lines", look at how rules have been applied | Transcript 4:39–5:03, 27:45–28:24 |
| R11 | Tool should be flexible: port state, USCG, class can all say something | Transcript 28:39 |
| R12 | New vessels only. Completed design (not half-built) | Transcript 31:38, 32:52 |
| R13 | Check **one system / one area at a time** (systems are separated in CAD) | Transcript 33:22–33:45 |
| R14 | **Dream feature:** "I add a cabin" → tool lists which rules now matter (Mikko named **SOLAS chapter II-2 regulation 13, means of escape**), what else is affected (water pressure, HVAC) and which engineer to notify | Transcript 37:49–40:28 |
| R15 | Privacy: everything provided is public. Production should run on **own servers or European compute**, local models fine (engineers have 32 GB RAM laptops). Cloud OK for hackathon. Auth/RBAC out of scope (nice-to-have) | Transcript 22:44–24:46 |
| R16 | Deliverables: **short demo, code repository, documentation that covers deployment** | Brief section 07 |
| R17 | Market: Solibri does deterministic checking for buildings, nothing exists for ships. Class societies would want it too | Transcript 19:09–19:33, 21:39 |

**Their evaluation slide (memorise this):**
- **Accuracy:** "Can we trust the assessment?"
- **Design Interpretation:** "Can it understand the design and show us why there is a problem?"
- **Quality & Usability:** "Is this a credible foundation for a useful engineering tool?"
- "A robust foundation matters more than a polished UI."

**Meyer contacts:** Eric Jacobsen (eric.jacobsen@meyerturku.fi, +358 50 409 1348), Mikko Vaahtoranta (mikko.vaahtoranta@meyerturku.fi). A principal naval architect (Mikko) also on site. Discord + "Joki": Sat 08:00–19:00, Sun from 08:00.

---

## 3. Decisions already made

- **2D drawings only. No 3D input.** NWD (Navisworks) is a closed format, shapes are faceted, export costs a night. Brief allows "drawings and/or 3D models".
  - Use the free **Autodesk Viewer** (browser) only to open the RCRV 3D model and measure with its ruler for the R5 proof. No code.
  - Pitch line: "The checker runs on a neutral ship model, so 3D/CAD data (OCX, IFC, Navisworks export) can plug in later."
- **Design data:** public **Oregon State RCRV** research vessel (~60 m, 33 berths). GA drawings (PDF). Backup GAs from the brief: DTU Dana, GO Sars, Atlantic Ship (anonymized).
- **Dropped ideas:** fictional ship from Excel, Safe Return to Port fire simulation, lifecycle timeline, cost clock, sister-ship rule drift. (Not asked for, no data.)
- **Rule set:** small (10–15 rules), stored as JSON/YAML, each value marked `verified` (from a real source) or `assumed` (allowed by Meyer, clearly labelled).
- **LLM:** provider-agnostic interface. Default for the demo can be any cloud model. Must also run with a **local European model** (e.g. Mistral via Ollama) to satisfy R15.

---

## 4. The concept

**Keel = "Solibri for ships, with AI that understands the drawings."**

Flow:
1. Engineer loads a GA deck drawing (vector PDF).
2. Keel extracts geometry: wall lines, door swing arcs, stairs, text labels, dimension texts.
3. Keel calibrates scale (title block scale or a known dimension) and **verifies** it against a second known dimension. Calibration error becomes the measurement tolerance.
4. Keel builds rooms (closed polygons) and assigns labels. AI maps label text/abbreviations to room categories (cabin, corridor, stair, mess, lab, machinery...). Low-confidence labels are marked for engineer confirmation.
5. Keel builds an escape graph: rooms connected by doors, leading to stairs/exits.
6. Deterministic checks run against the rule database.
7. Each finding: PASS / FAIL / NEEDS_REVIEW + red overlay on the drawing + measured vs required + rule reference + "how this rule is applied in practice" note.
8. Extras: scoped run (one deck / one rule family), defect injection + accuracy report, "add cabins" change impact.

---

## 5. Architecture

```
PDF (GA drawing)
   │  PyMuPDF: page.get_drawings(), page.get_text("dict")
   ▼
[extract]   raw primitives: lines, arcs/curves, rects, text spans (+ page coords)
   ▼
[calibrate] scale factor pt→mm, verified on 2nd dimension → tolerance_mm
   ▼
[model]     ShipModel (neutral, SI): Deck, Space(polygon, label, category),
            Door(hinge, width, swing side, connects A↔B), Stair, Exit
   │        shapely.polygonize for rooms; arcs → doors
   ▼
[label]     LLM maps labels → categories (+confidence)  ← only fuzzy step
   ▼
[graph]     networkx escape graph: spaces as nodes, doors as edges
   ▼
[rules]     rules/*.yaml  (id, source, ref, params, value, unit, status, interpretation_note)
   ▼
[checks]    pure Python functions, one per check type → Finding objects
   ▼
[verdict]   tolerance-aware policy → PASS / FAIL / NEEDS_REVIEW
   ▼
[report]    CLI table + JSON + annotated PDF/PNG overlay + web viewer
```

**Tech stack**
- Python 3.11, `pymupdf` (fitz), `shapely` 2.x, `networkx`, `pydantic`, `typer` (CLI), `fastapi` (API), `pytest`
- LLM: small adapter `keel/llm.py` with providers: `mistral` / `ollama` / any cloud model. JSON-schema outputs only.
- Web UI: simplest possible. Option A: FastAPI serves one HTML page with an SVG/PNG of the deck and clickable findings. Option B: small React/Next app. Start with A.
- Packaging: `Dockerfile` + `docker-compose.yml` (api + optional ollama). Deployment docs in `docs/DEPLOYMENT.md`.

**Repo structure**
```
keel/
  extract.py      # PDF → primitives
  calibrate.py    # scale detection + verification
  model.py        # pydantic ShipModel classes
  rooms.py        # polygonize, label assignment
  doors.py        # arc → door, swing side, connected spaces
  graph.py        # escape graph
  rules.py        # load + validate rules/*.yaml
  checks/         # one file per check type
  verdict.py      # PASS/FAIL/NEEDS_REVIEW policy
  inject.py       # defect injection
  impact.py       # "add cabins" change impact
  report.py       # CLI table, JSON, overlay image
  llm.py          # provider-agnostic LLM adapter
  cli.py          # typer entry point
api/main.py
web/index.html
rules/*.yaml
data/raw/ data/processed/  (drawings not committed if large)
tests/
docs/DEPLOYMENT.md docs/ARCHITECTURE.md docs/RULES.md
```

**CLI (target)**
```
keel extract data/raw/rcrv_ga.pdf --page 3 --out data/processed/deck2.json
keel check   data/processed/deck2.json --rules rules/ --scope escape
keel inject  data/processed/deck2.json --defect narrow_corridor --id C-201 --to 700mm
keel impact  data/processed/deck2.json --add-cabins 6 --near ST-2
keel eval    --baseline deck2.json --defects defects.yaml
keel serve
```

---

## 6. Verdict policy (the core of "accuracy")

For each numeric rule:
- `margin = measured - required` (sign depends on operator)
- `tol = calibration_tolerance_mm + extraction_tolerance_mm`
- **FAIL** only if: rule is numeric AND applicability confidence is high AND room/door classification confidence is high AND violation > `tol`
- **PASS** if requirement met by more than `tol`
- **NEEDS_REVIEW** otherwise (borderline, low confidence, or rule type = `judgment`)

Rules of type `judgment` (vague SOLAS wording) **never auto-fail**. They show the evidence and the interpretation note and ask the engineer.

---

## 7. Rule database

Schema (YAML):
```yaml
- id: ESC-CORRIDOR-WIDTH
  title: Minimum clear width of corridors on escape routes
  source: "SOLAS II-2/13 + FSS Code ch.13"     # where the value comes from
  ref_url: ""
  type: numeric            # numeric | geometric | judgment
  applies_to: [corridor]
  parameter: clear_width
  operator: ">="
  value_mm: 900
  value_status: assumed     # verified | assumed
  interpretation_note: "How it is applied in practice (IACS UI / MSC circular / class guidance), our own words."
  check: corridor_width
```

Starter rule list (fill values from sources; anything not verified stays `assumed`):

| id | Check | Value | Status |
|---|---|---|---|
| ACC-DOOR-CLEAR | Door clear opening width (ADA 2010 Standards 404.2.3) | ≥ 815 mm (32 in) | verify in source |
| ACC-ROUTE-WIDTH | Accessible route clear width (ADA 403.5.1) | ≥ 915 mm (36 in) | verify in source |
| ACC-TURNING | Turning circle in accessible spaces (ADA 304.3.1) | ≥ 1525 mm (60 in) | verify in source |
| ESC-CORRIDOR-WIDTH | Corridor width on escape routes (SOLAS II-2/13, FSS Code ch.13) | take from source | assumed until verified |
| ESC-STAIR-WIDTH | Stair clear width, incl. capacity-based minimum (FSS Code ch.13) | take from source | assumed until verified |
| ESC-DOOR-SWING | Doors on escape routes open in direction of escape; cabin doors excepted (SOLAS II-2/13) | geometric | verify paragraph |
| ESC-TWO-MEANS | At least two means of escape from each area (SOLAS II-2/13) | graph | verify scope |
| ESC-DEAD-END | Max dead-end corridor length (SOLAS II-2/13) | take from source | assumed until verified |
| LL-GUARDRAIL | Bulwark/guard rail height ≥ 1 m (Load Line Convention reg. 25) | ≥ 1000 mm | needs profile drawing, stretch |
| CLASS-xxx | 1–2 numeric DNV rules relevant to arrangement (DNV rules are free online) | from DNV | pick Sat |

Note: RCRV is a research vessel, not a cruise ship, so some rules are applied **for demonstration**. Say so openly. Meyer is fine with made-up parameters.

---

## 8. Geometry algorithms (how each check measures)

- **Scale:** read title block scale text (e.g. `1/4" = 1'-0"` or `1:50`). Convert PDF points → mm. Verify using a printed dimension (dimension text + its line length). Store `tolerance_mm`.
- **Rooms:** collect wall line segments, snap endpoints (small tolerance), `shapely.ops.polygonize` → polygons. Assign each text label to the polygon containing it. Walls are often double lines: use inner faces.
- **Corridor clear width:** narrowest passage = largest `w` such that `polygon.buffer(-w/2)` still connects the corridor's entry and exit (binary search). Also report the location of the bottleneck for the overlay.
- **Doors:** door = quarter-circle arc + leaf line. Radius ≈ leaf width (clear width ≈ radius minus frame allowance, mark as assumption). Hinge = arc centre. Swing side = the space the arc lies in.
- **Door swing vs escape direction:** compute shortest path from each space to nearest exit/stair in the escape graph. For each door on that path, the arc must lie on the "next room" side. Cabin doors are exempt.
- **Two means of escape:** for each space/zone, count node-disjoint paths to different exits (networkx). < 2 → finding.
- **Dead ends:** corridor segments that lead to no exit; length along centreline.
- **Stair capacity (for "add cabins"):** persons from cabin labels/berths → required stair width by the capacity rule → compare with measured stair width.

---

## 9. Accuracy proof (demo + submission)

1. **Baseline run** on the original deck → expect **0 FAIL**. Any FAIL on the original must be investigated before the demo (either a real issue → NEEDS_REVIEW, or a bug).
2. **Defect injection** (`keel inject`), at model level first, optionally also redrawn on the PDF for visuals:
   - narrow a corridor below the limit
   - flip a door swing on an escape route
   - remove the second exit of a space
   - shrink a door below 815 mm
   - lengthen a dead-end corridor
   - add cabins until stair capacity fails
3. **Eval table** (`keel eval`): injected N, found, missed, false positives on baseline. Target: all found, 0 false positives. Put the real numbers in README and video.
4. **Ruler check:** same corridor measured in a normal PDF viewer / Autodesk Viewer → matches Keel within tolerance.
5. Ask the Meyer naval architect on Saturday to confirm verdicts on one deck → quote it in the pitch.

---

## 10. "Add a cabin" change impact (their favourite)

Input: add N cabins (persons) at a location.
Output:
1. Re-run scoped checks for affected spaces (escape routes, stair capacity, door swing, two means).
2. List rules that now apply (e.g. SOLAS II-2/13 means of escape) with reason.
3. List other disciplines to notify, from a simple dependency map (`impact_map.yaml`): cabin → HVAC (air supply), fresh water, sanitation, electrical, fire detection, lifesaving capacity. These are notifications, not calculations (no system data). Say this honestly.
Demo: add 6 cabins → stair capacity FAIL → notify HVAC + water engineers.

---

## 11. Timeline and roles (team up to 5)

| When | Goal |
|---|---|
| Fri night | Get RCRV GA PDFs. Confirm **vector** (`len(page.get_drawings())` large, text extractable, door arcs visible, scale present). Extraction + calibration working on one deck. Rules YAML v1. Repo + CI + deploy skeleton |
| Sat 08–12 | Rooms, labels, doors, escape graph. First checks running in CLI |
| Sat 12–14 | Verdict policy, report JSON, overlay image. **End-to-end flow works (ugly is fine)** |
| Sat 14–16 | Show Meyer at Joki. Ask: right focus? which 5 rules? confirm verdicts on one deck? |
| Sat 16–24 | Defect injection + eval table, add-cabins impact, scoped runs, web viewer, LLM labelling with local model option |
| Sun 00–07 | README, ARCHITECTURE.md, DEPLOYMENT.md, Docker, record 2-min video, freeze main, submit all fields |

Roles: A geometry/extraction · B rules + checks + verdict · C LLM labelling + impact + eval · D web viewer + overlay · E docs, video, Devpost fields, mentor contact.

If GA PDFs are **raster only**: try other GAs from the brief. Last resort: vision LLM for labels + manual scale calibration, accept lower accuracy and say so.

---

## 12. Submission requirements

Since AI Devpost (13 fields): project name, challenge track, short description, problem statement, solution, technical architecture, working prototype (live link or clear test instructions), code repo, **demo video ≤ 2 min**, work done during event, pre-existing assets, responsible implementation, next steps.
Meyer additionally: short demo, repo, **documentation covering deployment**.

Since AI judging weights: Technical Execution 30%, Challenge Fit & Impact 25%, Innovation 20%, Prototype & Demo 15%, Responsible Implementation & Feasibility 10%. Finalists come from peer voting (each builder does 20 pairwise comparisons Sun 10–12): the video thumbnail and first 10 seconds must be instantly clear.

Special prizes to aim for: Meyer challenge winner, Best Technical Execution, Best Responsible AI (on-prem/EU model option, human decides, no auto-certification, evidence on every finding).

---

## 13. Pitch / video (2 min)

- 0:00 Hook: "A door that opens the wrong way costs one hour to fix in design and a fortune in production. Meyer checks thousands of these by hand."
- 0:15 Load RCRV deck. Keel reads walls, doors, rooms, escape routes.
- 0:35 Baseline: 0 FAIL. Inject defects live: narrow corridor, flipped door. Keel flags both, red overlay, rule + measured vs required.
- 1:00 Ruler proof: same corridor in the viewer = same value.
- 1:15 Add 6 cabins → stair capacity fails → notify HVAC + water.
- 1:35 Eval table (real numbers). Trust: AI reads, code measures, engineer decides; runs on a local European model.
- 1:50 "Keel. Solibri for ships." Next steps: 3D/OCX input, full rule library, Meyer pilot.

---

## 14. Open questions / risks

- Are RCRV GA PDFs vector? (blocks everything; check first)
- Units: inches vs metres (convert on input)
- Wall double lines and symbols may confuse polygonize → snapping tolerance, filter by line width/layer
- Exact rule values for SOLAS/FSS → verify or mark `assumed`
- Door clear width vs leaf width → document assumption
- Keep LLM out of measurements (rule 1)

## 15. Reference links

- Since AI Devpost: https://sinceai2026.devpost.com/
- RCRV design files: https://ceoas.oregonstate.edu/regional-class-research-vessel-ship-design
- Other GAs: links in Meyer brief section 05
- DNV rules (free): https://www.dnv.com/rules-standards
- Autodesk Viewer (free, open NWD + ruler): https://viewer.autodesk.com
