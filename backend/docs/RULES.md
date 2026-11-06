# Rule database

Rules are YAML files in `rules/`, summarised in our own words. **RCRV is a research vessel, not a
cruise ship, so these rules are applied for demonstration.**

- `verified`: the value was checked in the cited document
- `assumed`: a placeholder, which Meyer allowed for the hackathon

| Rule | Requirement | Status | Checked in |
|---|---|---|---|
| ESC-CORRIDOR-WIDTH | At least 900 mm | assumed | SOLAS defers to the FSS Code, which we have not read in the original |
| ESC-STAIR-WIDTH | At least 900 mm | assumed | Same |
| ESC-STAIR-CAPACITY | (N1 + N2) × 10 mm | verified | [IMO Res. A.757(18)](https://wwwcdn.imo.org/localresources/en/KnowledgeCentre/IndexofIMOResolutions/AssemblyDocuments/A.757(18).pdf) |
| ESC-DOOR-WIDTH | At least 700 mm | assumed | No source |
| ESC-DOOR-SWING | Open towards escape; cabin doors exempt | verified | SOLAS II-2/13.3.1.5 in the [UK MCA copy](https://assets.publishing.service.gov.uk/media/5a80f3c6ed915d74e33fd543/Regulation_13_-_Means_of_Escape.pdf) |
| ESC-TWO-MEANS | At least 2 routes | verified | SOLAS II-2/13.3.2.2 in the same copy. Written for passenger ships, per zone |
| ESC-DEAD-END | At most 7 m; shallow recess allowed | verified | SOLAS II-2/13.3.3.4 and 13.3.1 in the same copy. Sits in the cargo ship section |
| ACC-DOOR-CLEAR | At least 815 mm | verified | [ADA 2010 Standards](https://www.access-board.gov/ada/) 404.2.3 |
| ACC-ROUTE-WIDTH | At least 915 mm | verified | ADA 403.5.1 |
| ACC-TURNING | At least 1525 mm | verified | ADA 304.3.1 |

The MCA copy may not be the latest consolidated SOLAS text, so confirm paragraph numbers before
relying on them.

## ADA rules are opt-in

The drawing does not mark accessible routes. ADA rules run only on spaces marked `accessible: true`
in the deck config. Most doors here are about 790 mm clear, under the 815 mm ADA minimum, so applying
ADA to the whole ship would fail a vessel never designed to meet it everywhere.

## Not implemented

From the brief's starter list: `LL-GUARDRAIL` needs a profile drawing, and `CLASS-xxx` (DNV) values
were not selected. Rule type `judgment` is supported by the schema, but no rule uses it yet.

## Adding a rule

Add an entry to a YAML file. If it needs a new measurement, add a function in `keel/checks/`, register
it in `CHECKS`, and write a test. Unknown fields and duplicate ids are rejected on load.
