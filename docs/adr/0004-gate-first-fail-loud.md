# ADR-0004: Gate before work; fail loudly on exhaustion

Status: accepted
Date: 2026-09-08
Decider: Andrew Nelson
Time spent: 10 min

## Context
Two failure modes end prototype demos. First: the system answers a question it
should have refused or clarified, and answers it fluently. Second: something
fails mid-chain, a retry loop papers over it, and a plausible partial result is
presented as complete. Both are worse than an error, because both are invisible.

## Decision
`gate_agent` runs first and has three outcomes — PROCEED, ASK (exactly one
question), BLOCK — and deliberately holds **zero** data access, so it decides
without being able to peek. Rules live in `src/policies/gating.yaml` with stable
ids. Retries are capped at 2 and only for genuinely transient classes; a BLOCK,
a permission denial, and an INDETERMINATE are decisions, not failures, and are
never retried. On exhaustion the run is marked FAILED, a row lands in
`ops.failure_log` and `ops.hitl_queue`, a notification fires, and **no default
value is substituted**.

## Alternatives considered
| option | why not |
|---|---|
| Confidence threshold, answer anyway below it | Calibration is the thing we have least evidence for |
| Retry until something parses | Manufactures a plausible answer from a broken run |
| Gate after retrieval | Sensitive data is already in context; the gate is decorative |

## Consequences
**We gain:** every refusal is attributable to a rule id, and every failure is
visible in `ops.*` rather than smoothed over.
**We lose:** the system will sometimes ask when a confident guess would have
been right, which reads as less impressive in a live demo.
**We revisit when:** ASK rate exceeds ~15% of realistic traffic.

## Evidence
`src/policies/gating.yaml`, `src/policies/retry.yaml`, golden cases
GATE-101..106, RTY-601, RTY-602; `tests/test_contracts.py::test_exhaustion_fails_loud`.
