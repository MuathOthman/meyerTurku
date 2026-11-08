# Keel

### Compliance checks for ship drawings

**AI reads the drawing. Code measures it. The engineer decides.**

Keel was built for the **Meyer Turku challenge** at **Since AI Hackathon 2026**. It reads a ship's
deck plans, finds the rooms, corridors, stairs and doors on them, and checks them against
international maritime safety rules. It points out what may not comply, shows why, and leaves
every final decision to a qualified engineer.

---

## Contents

1. [The problem](#1-the-problem)
2. [What Keel does](#2-what-keel-does)
3. [How it works, step by step](#3-how-it-works-step-by-step)
4. [What Keel checks](#4-what-keel-checks)
5. [How Keel uses AI, and why it is held back](#5-how-keel-uses-ai-and-why-it-is-held-back)
6. [Using the app](#6-using-the-app)
7. [What Keel is not](#7-what-keel-is-not)
8. [The demo ship](#8-the-demo-ship)
9. [Running Keel on your own computer](#9-running-keel-on-your-own-computer)
10. [Running Keel as a server or in the cloud](#10-running-keel-as-a-server-or-in-the-cloud)
11. [Tests](#11-tests)
12. [Project layout](#12-project-layout)
13. [Technology](#13-technology)
14. [Glossary](#14-glossary)
15. [Further reading](#15-further-reading)

---

## 1. The problem

Before a ship is built, its design must satisfy many international rules. They cover how wide an
escape corridor must be, how many ways out an engine room needs, which way doors must open, where
the emergency generator may stand, and much more. The rules come from several sources:

- **SOLAS**, the International Convention for the Safety of Life at Sea
- **MARPOL**, the convention on pollution from ships
- **COLREG**, the rules on navigation lights and collision avoidance
- **The Load Line Convention**, on freeboard and guard rails
- **The Ballast Water Management Convention**
- **Classification society rules**, such as DNV's
- **Accessibility guidelines** for passenger ships (ADA, PVAG)

A ship's layout is shown on a **General Arrangement (GA) plan**: a large drawing with one plan of
each deck, seen from above. Today engineers check these drawings against the rules largely by
hand. They read every label, measure every corridor and stair on the drawing, and look up each
rule. It is slow, repetitive and easy to get wrong late at night before a deadline, and a mistake
found after construction starts is very expensive to fix.

## 2. What Keel does

You upload a GA plan as a PDF or an image. Keel then:

1. **Finds each deck** on the sheet, even when several decks are drawn side by side.
2. **Reads the rooms**: cabins, corridors, stairs, engine rooms, galleys, stores and so on.
3. **Measures** the widths and distances the rules care about, using the drawing's scale.
4. **Checks each rule** and gives each item one of three results:
   - **Meets the rule**
   - **Does not meet the rule**
   - **An engineer should decide**, when the measurement is too close to call or Keel could not
     measure it
5. **Shows its work.** For every result you see the measured value, the limit, the regulation it
   comes from, the area on the drawing, and any assumption Keel made.
6. **Records the engineer's decision.** The engineer accepts, rejects or asks for more
   information, and each decision is saved in a change log with the reason.

It also looks at the **whole ship**. It reads the main dimensions from the title block and works
out the limits the ship must meet, for example the minimum height and spacing of the masthead
lights under COLREG. It also checks whether the spaces the rules require appear anywhere on the
drawing, such as a sewage system, a sludge tank, an emergency generator or a steering gear room.

## 3. How it works, step by step

```
  Drawing (PDF)
       │
       ▼
  1. Split the sheet into decks ........ code
  2. Read the lines, text and symbols .. code
  3. Name each room .................... AI, checked against the printed labels
  4. Find corridors, stairs and doors .. code
  5. Measure ........................... code, using the drawing's scale
  6. Check each rule ................... code
  7. Look where code could not measure . AI, as evidence only
  8. Decide ............................ the engineer
```

**Steps 1 and 2: reading the drawing.** A PDF drawing made by design software contains the exact
lines and text the designer drew. Keel reads them directly, so there is no guessing from pixels.
For scanned images it uses text recognition (OCR) instead.

**Step 3: naming rooms.** Room labels on drawings are small, abbreviated and sometimes garbled.
Keel first trusts the labels printed on the drawing. Where a label is unclear or missing, an AI
vision model suggests a name. Keel also sets aside areas that are not rooms, such as tanks, voids,
furniture, hatches and small gaps between lines, and lists them with the reason.

**Steps 4 and 5: measuring.** Keel works out the drawing's scale and checks it against a dimension
printed on the drawing. On the demo ship, a dimension printed as 1020 mm measures as 1021 mm. Each
measurement carries a tolerance, so a corridor that is only a few millimetres off the limit is
marked **too close to call**, not failed.

**Step 6: checking rules.** Every rule is stored as plain data: the limit, the regulation, the
clause and a link to the source. A rule only applies to the ship types it was written for, so
passenger-ship accessibility rules are not applied to a research vessel.

**Step 7: AI looks where code is blind.** Some checks need something Keel could not find, for
example doors drawn in an unusual way. For these, Keel shows the AI that part of the drawing,
outlined in red, and asks one plain question, such as *"Count the separate ways out of this
space."* The answer is shown to the engineer as evidence, marked "AI looked", and it never passes
or fails anything on its own.

**Step 8: the engineer decides.** Nothing Keel says is final. The engineer reviews each item,
looks at the outlined area on the drawing, and accepts or rejects it.

## 4. What Keel checks

### On each deck

| Check | What is measured | Source |
|---|---|---|
| Corridor width | Clear width of corridors on escape routes | FSS Code ch. 13, via SOLAS II-2/13 |
| Stair width | Clear width of stairways on escape routes | FSS Code ch. 13 |
| Stair capacity | Whether a stair is wide enough for the people it serves | IMO Resolution A.757(18) |
| Door width | Clear width of doors on escape routes | Placeholder value, marked **Assumed** in the app (FSS Code ch. 13 for cargo ships) |
| Door swing | Escape doors open in the direction of escape | SOLAS II-2/13.3.1.5 |
| Two ways out | At least two means of escape from each accommodation area | SOLAS II-2/13.3.2.2 and 13.3.3.1 |
| Dead ends | Maximum length of a corridor that leads nowhere | SOLAS II-2/13.3.3.4 |
| Engine room escape | Two widely separated ways out of a main machinery space | SOLAS II-2/13.4.2.1 |
| Other machinery spaces | Ways out of smaller machinery rooms | SOLAS II-2/13.4.2.3 |
| Sole stairway | Rules for a stair that is the only way out | DNV Rules for Ships Pt.5 Ch.2 Sec.2 E 602 |
| Galley lobby | A lobby between a galley and a stairway | DNV Rules for Ships Pt.5 Ch.2 Sec.2 E 604 |
| Accessibility | Door widths, route widths, turning space | ADA 2010 and PVAG (passenger ships only) |

### On the whole ship

| Check | What Keel does |
|---|---|
| COLREG navigation lights | Works out the required masthead light heights, spacing and visibility from the length and breadth on the title block |
| MARPOL sewage, oil residue, oil filtering, garbage | Looks for these spaces on every deck and shows where they are |
| Ballast water management | Looks for a ballast water treatment system |
| SOLAS emergency power, steering gear, survival craft, emergency exits | Looks for these spaces and shows where they are |
| Load Line, Polar Code, current class rules | Listed for checking by hand, because a deck plan does not show them |

A space Keel cannot find is shown as **Not found**, not as a failure. It may be on another drawing.

The full list of rules, with each value and its source, is in the app under **Rules** and in
[backend/docs/RULES.md](backend/docs/RULES.md).

## 5. How Keel uses AI, and why it is held back

AI is good at **reading** drawings: recognising that a smudged "ENG. RM" is an engine room, or
counting the doors around a room. It is not reliable at **measuring** millimetres from an image.
Keel is built around that difference.

| Task | Done by |
|---|---|
| Reading printed labels and lines | Code |
| Naming unclear rooms | AI, with its confidence capped below that of printed labels |
| Every measurement | Code |
| Every pass or fail | Code |
| Looking at what code could not measure | AI, shown as evidence only |
| Every final decision | The engineer |

In practice this means:

- AI names are marked as AI names and are never trusted as much as a label printed on the drawing.
- An AI answer can only ever produce **"An engineer should decide"**, never "Meets the rule" or
  "Does not meet the rule".
- Keel works without AI. Measurements and verdicts stay exactly the same, only room naming is less
  complete and the "AI looked" evidence is missing.
- AI answers are cached, so the same drawing gives the same result each time.

Keel uses **OpenAI GPT-5.5** with vision by default. Google Gemini and local models are supported
in the code.

## 6. Using the app

1. **Sign up and log in.**
2. **Create a project** for a ship and choose its type, such as cargo or passenger. The type
   decides which rules apply.
3. **Upload the drawing.** Keel splits it into decks and analyses each one. Progress is shown live.
4. **Open a deck.** The screen has two parts:
   - **On the left (a quarter of the screen):** the list of checks, grouped by what to do:
     *Fails*, *Review*, *AI looked: confirm*, *Check by hand*, and *Passes*.
   - **On the right:** the selected item in detail: the drawing with the area outlined, the
     measured value against the limit, why it matters, the regulation with a link, the
     assumptions, a suggested fix, and the decision buttons.
5. **Decide.** Press **Accept finding**, **Need info** or **Reject**, with an optional reason. The
   decision is saved in the **Change log**, and items checked by hand show as done.
6. **Rooms tab.** Every room Keel found, and a list of the areas it set aside as not rooms, each
   with the reason.
7. **Whole ship.** Ship-wide limits and required spaces, grouped by regulation, with links to the
   decks where each space appears.

## 7. What Keel is not

- **It is not an approval.** Keel does not certify a ship. Approval comes from the flag state and
  the classification society.
- **It does not replace the engineer.** It does the reading and measuring so the engineer can
  spend their time on judgement.
- **It only sees what is on the drawing.** Heights, structure and anything shown only on profiles
  or sections are listed for checking by hand.
- **Some rule values are placeholders.** Where a limit has not been checked against the original
  text, the app marks it **Assumed** and warns not to rely on it.

## 8. The demo ship

The demonstration drawing is an anonymised GA plan of a **60 m fishery research vessel for Arctic
operation**:

| | |
|---|---|
| Length overall | 60.00 m |
| Length between perpendiculars | 52.20 m |
| Breadth | 15.00 m |
| Frame spacing | 600 mm |
| Drawing scale | 1:125 |
| Decks on the sheet | 8 |

From this sheet Keel works out, among other things, that a second masthead light is required
because the ship is 50 m or longer, that the masthead lights must be at least 30 m apart, and that
the forward masthead light must be at least 12 m above the hull. It also flags the Polar Code for
checking by hand, because the title names Arctic operation.

---

## 9. Running Keel on your own computer

*This part is for developers.*

### What you need

- Python 3.11 or newer
- Node.js 20 or newer
- MongoDB, either on your computer or a hosted database such as MongoDB Atlas. It stores user
  accounts.
- Optional: an OpenAI API key for room naming and "AI looked" evidence

### First-time setup

```bash
# Backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
scripts/get_data.sh
.venv/bin/keel extract data/decks/rcrv_01_level.yaml --out data/processed/deck01.json
cd ..

# Settings
cp .env.example .env
```

Open `.env` and fill in what you need:

| Setting | What it is |
|---|---|
| `api_chatgpt` | OpenAI API key. Optional. Without it, Keel runs with no AI |
| `api_gemini` | Google Gemini key, if you use Gemini instead |
| `KEEL_LLM_PROVIDER`, `KEEL_LLM_MODEL` | Choose the AI provider and model |
| `MONGODB_URI` | Database for user accounts. Defaults to MongoDB on this computer |

**Never commit `.env`.** It is listed in `.gitignore`.

To run MongoDB on a Mac:

```bash
brew tap mongodb/brew
brew trust --formula mongodb/brew/mongodb-community
brew install mongodb-community --without-mongodb-database-tools
brew services start mongodb-community
```

### Start the app

From the project folder:

```bash
./dev.sh
```

Then open **http://localhost:5173**. The backend runs on port 8000 and restarts when its code
changes.

> Changing backend code restarts the server, which stops any analysis that is running. Wait for
> uploads to finish before editing the backend.

## 10. Running Keel as a server or in the cloud

The backend can serve the built web app itself, so a demo needs one process and one port:

```bash
npm --prefix frontend install && npm --prefix frontend run build
cd backend && .venv/bin/keel serve      # http://127.0.0.1:8000
```

With Docker:

```bash
cd backend && docker compose up --build
```

To deploy on **Red Hat OpenShift**, including MongoDB, see [deploy/README.md](deploy/README.md)
and [backend/docs/DEPLOYMENT.md](backend/docs/DEPLOYMENT.md).

## 11. Tests

```bash
cd backend && .venv/bin/python -m pytest     # rules, geometry, room naming, AI handling
cd frontend && npm test                       # the web app
```

The backend tests run with a fake AI, so they need no API key and give the same result every time.

## 12. Project layout

```
meyerTurku/
├── backend/                Reads drawings, measures, checks rules (Python)
│   ├── keel/               The engine: extraction, geometry, room naming, checks
│   │   ├── checks/         One file per family of checks (escape, machinery, accessibility)
│   │   ├── ai_look.py      Asks the AI about checks code could not measure
│   │   └── ship.py         Whole-ship checks from the title block
│   ├── rules/              The rules as data, with limits and sources
│   ├── config/             Which rules apply to which ship and space types
│   ├── api/                The web API the app talks to
│   ├── tests/              Automated tests
│   └── docs/               Architecture, rules and deployment notes
├── frontend/               The web app (React). Shows results, holds no rule logic
├── deploy/                 OpenShift deployment files
└── dev.sh                  Starts everything for development
```

All compliance logic lives in the backend. The web app only shows what the backend found, so a
result is the same wherever it is viewed.

## 13. Technology

| Area | Tools |
|---|---|
| Backend | Python, FastAPI, PyMuPDF (PDF reading), Shapely (geometry), OpenCV and RapidOCR (images) |
| AI | OpenAI GPT-5.5 with vision. Gemini and local models are supported |
| Frontend | React, TypeScript, Vite, TanStack Router, TanStack Query |
| Data | MongoDB Atlas for accounts |
| Deployment | Docker, Red Hat OpenShift |
| Testing | pytest, Vitest |

## 14. Glossary

| Term | Meaning |
|---|---|
| **GA plan** | General Arrangement plan: the drawing that shows the layout of every deck |
| **Deck** | One floor of the ship |
| **Means of escape** | A route people can use to leave a space in an emergency |
| **Dead end** | A corridor that leads nowhere, so people must turn back |
| **Machinery space of category A** | A space with main engines or large oil-fired machinery, such as the engine room |
| **Classification society** | An organisation, such as DNV, that sets technical rules for ships and checks they are met |
| **Flag state** | The country a ship is registered in, which certifies it |
| **Tolerance** | How precisely a value can be measured from the drawing. A result within it is too close to call |
| **Title block** | The box on a drawing with the ship's name, main dimensions and scale |
| **LOA / LPP** | Length overall / length between perpendiculars |

## 15. Further reading

- [backend/README.md](backend/README.md): the backend in detail
- [backend/docs/ARCHITECTURE.md](backend/docs/ARCHITECTURE.md): how the parts fit together
- [backend/docs/RULES.md](backend/docs/RULES.md): every rule, its value and its source
- [backend/docs/DEPLOYMENT.md](backend/docs/DEPLOYMENT.md) and [deploy/README.md](deploy/README.md): deployment
- [frontend/README.md](frontend/README.md): the web app

---

*Keel is a hackathon prototype built for the Meyer Turku challenge at Since AI Hackathon 2026. It
supports engineers. It does not certify ships.*
