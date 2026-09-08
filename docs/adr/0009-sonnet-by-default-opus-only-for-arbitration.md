# ADR-0009: Sonnet for every source pull; Opus only for arbitration and falsification

Status: accepted
Date: 2026-09-08
Decider: Andrew Nelson
Time spent: 6

## Context
Model routing lived in `scripts/cost_model.py` while `AGENT_REGISTRY.yaml` knew
nothing about it. Two sources of truth drift, and the ROI slide then describes a
system that does not exist. Separately, nothing said which agents may spend the
expensive model.

## Decision
Every agent declares `model` in the registry, and `cost_model.py` reads it.
Three tiers: `none` for deterministic code paths (the quote path is one — an LLM
formatting a bid/ask is pure loss), `claude-sonnet-5` as the default for every
pull from a third-party source or an internal DB, and `claude-opus-5` restricted
to `red_team_agent`, `discrepancy_agent`, `heuristic_override_agent`, and the
desk orchestrator's commit decision. Retrieval errors are cheap to detect;
judgment errors are not, and that is the whole basis for the split.

## Alternatives considered
| option | why not |
|---|---|
| Opus everywhere | 42% more per task for no measured quality gain on retrieval |
| Haiku for the gate | plausible, but a gate miss is the most expensive error here; measure before moving it |
| Keep routing in the cost script | the drift that produced this ADR |

## Consequences
**We gain:** one source of truth, a routing rule stateable in one sentence, and a
measured $/task.
**We lose:** the registry now carries an operational concern next to a design
concern, so a model change is a registry change and gets test-gated. We also
give up per-call adaptive routing, which is likely the bigger long-run lever.
**We revisit when:** eval data shows sonnet failing a retrieval class, or shows
haiku holding on the gate.

## Evidence
`tests/test_contracts.py::test_every_agent_declares_a_model`,
`::test_opus_is_reserved_for_arbitration_and_falsification`,
`::test_every_agent_has_a_cost_profile`. `make cost VOL=5000`.
