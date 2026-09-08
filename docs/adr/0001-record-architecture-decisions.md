# ADR-0001: Record architecture decisions as short ADRs during the sprint

Status: accepted
Date: 2026-09-08
Decider: Andrew Nelson
Time spent: 5 min

## Context
A 2.5-hour prototype is judged on the readout, not the code. In the debrief the
question is always "why did you do it that way?" — and reconstructing rationale
from memory under time pressure produces worse answers than the decisions
deserved. Slides 1, 3, and 7 of any readout are ADRs the interviewer has not
read yet.

## Decision
Every non-obvious choice gets a ≤15-line ADR at the moment it is made. ADRs are
numbered, dated, and state what was given up. `scripts/turn_tick.py` scrapes
their titles and statuses into the presentation prompt automatically, so writing
one is also deck preparation.

## Alternatives considered
| option | why not |
|---|---|
| Write it up at the end | The reasoning is gone by then; you reconstruct a flattering version |
| Inline code comments | Not reviewable as a set; the interviewer cannot skim them |
| No record | The most common way a good decision reads as an accident |

## Consequences
**We gain:** defensible answers, and a deck outline that assembles itself.
**We lose:** ~3 minutes per decision — roughly 15 minutes of a 150-minute sprint.
**We revisit when:** ADR writing exceeds 10% of sprint time.

## Evidence
`scripts/turn_tick.py::collect` reads `docs/adr/*.md`; the titles appear in
`docs/presentation/PRESENTATION_PROMPT.txt`.
