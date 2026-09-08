# Build plan: <problem name>

Fill in T-0 → T-10. Everything downstream flows from this page.

## The problem, in one sentence
> 

## Who asks, and what they do with the answer
| actor | task | frequency | cost of a wrong answer |
|---|---|---|---|
| | | | |

## Entities
| entity | source system(s) | id field | canonical? | notes |
|---|---|---|---|---|
| | | | | |

Anything appearing in two source systems needs a `core.entity_xref` row.

## Tasks → agents
One line each, one verb, no "and". If a row needs "and", split the row.

| agent | single task | data scope | write scope | escalates when |
|---|---|---|---|---|
| | | | `[]` | |

## Sensitive / indeterminate surface
| situation | gate | rule id |
|---|---|---|
| | BLOCK / ASK | |

## Unwritten rules (ask the interviewer directly)
> "What rule do your people follow that isn't in the written policy?"

| rule | overrides | owner | confidence |
|---|---|---|---|
| | | | |

## Metrics
| metric | definition | grain | source |
|---|---|---|---|
| | | | |

Copy these into `docs/coding/DATA_MODEL.md` — a metric absent there returns ASK.

## Explicitly not building
1. 
2. 
3. 

## Success criteria for the demo
- [ ] smoke tier 100%
- [ ] safety categories 100%
- [ ] one end-to-end path a human can watch
- [ ] one deliberate escalation, shown on purpose
