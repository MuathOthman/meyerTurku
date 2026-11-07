# Rule database

Rules are YAML files in `rules/`, summarised in our own words. **RCRV is a research vessel, not a
cruise ship, so these rules are applied for demonstration.**

- `verified`: the value was checked in the cited document
- `assumed`: a placeholder, which Meyer allowed for the hackathon

| Rule | Requirement | Status | Checked in |
|---|---|---|---|
| ESC-CORRIDOR-WIDTH | Passenger 900 mm, cargo 700 mm | verified | [FSS Code ch.13, passenger](https://imorules.com/GUID-AFE2E2CA-D9CB-484A-969A-385A1B19DFDD.html) 2.3.1 and [cargo](https://www.imorules.com/GUID-06E84CE3-61E4-42AA-B917-E953D46A4411.html), in a third-party copy |
| ESC-STAIR-WIDTH | Passenger 900 mm, cargo 700 mm | verified | Same, passenger 2.1.1 |
| ESC-STAIR-CAPACITY | (N1 + N2) × 10 mm | verified | [IMO Res. A.757(18)](https://wwwcdn.imo.org/localresources/en/KnowledgeCentre/IndexofIMOResolutions/AssemblyDocuments/A.757(18).pdf) |
| ESC-DOOR-WIDTH | Cargo 700 mm verified. Passenger 700 mm assumed | mixed | FSS Code ch.13. Passenger ships size doorways as stairways, so 700 mm there is a placeholder |
| ESC-DOOR-SWING | Open towards escape; cabin doors exempt | verified | SOLAS II-2/13.3.1.5 in the [UK MCA copy](https://assets.publishing.service.gov.uk/media/5a80f3c6ed915d74e33fd543/Regulation_13_-_Means_of_Escape.pdf) |
| ESC-TWO-MEANS | At least 2 routes | verified | SOLAS II-2/13.3.2.2 in the same copy. Written for passenger ships, per zone |
| ESC-DEAD-END | At most 7 m; shallow recess allowed | verified | SOLAS II-2/13.3.3.4 and 13.3.1 in the same copy. Sits in the cargo ship section |
| CLASS-DNV-SOLE-STAIR | Sole-escape stair at least 800 mm | verified | [DNV Rules for Ships, July 2015](https://rules.dnv.com/docs/pdf/DNVPM/rulesship/2015-07/ts502.pdf), Pt.5 Ch.2 Sec.2 E 602. Passenger ships. Goes to review, never FAIL |
| CLASS-DNV-GALLEY-LOBBY | Galley or laundry lobby to a stair at least 900 mm and 4.5 m² | verified | Same, E 604. Passenger ships. The required fire hose station is not checked, so it always goes to review |
| ACC-DOOR-CLEAR | At least 815 mm | verified | [ADA 2010 Standards](https://www.access-board.gov/ada/) 404.2.3 |
| ACC-ROUTE-WIDTH | At least 915 mm | verified | ADA 403.5.1 |
| ACC-TURNING | At least 1525 mm | verified | ADA 304.3.1 |

The MCA copy may not be the latest consolidated SOLAS text, so confirm paragraph numbers before
relying on them. The FSS Code values come from imorules.com, a third-party copy of the 2024 text,
because the IMO original is not free. Confirm them in the original.

The ship type is chosen at upload and sets these limits. The RCRV demo uses passenger limits for
demonstration. The two DNV rules apply to passenger ships only.

The DNV values come from the July 2015 edition, the newest readable without a login. It predates
the current DNV-RU-SHIP rules, so check the current edition before relying on them.

## ADA rules are opt-in

The drawing does not mark accessible routes. ADA rules run only on spaces marked `accessible: true`
in the deck config. Most doors here are about 790 mm clear, under the 815 mm ADA minimum, so applying
ADA to the whole ship would fail a vessel never designed to meet it everywhere.

## Not implemented

From the brief's starter list: `LL-GUARDRAIL` needs a profile drawing. Rule type `judgment` is supported by the schema, but no rule uses it yet.

## Adding a rule

Add an entry to a YAML file. If it needs a new measurement, add a function in `keel/checks/`, register
it in `CHECKS`, and write a test. Unknown fields and duplicate ids are rejected on load.
