# Security and access model

The claim to defend in the readout: **an agent's blast radius is bounded by its
GRANTs, not by its instructions.**

## Layers

| layer | mechanism | fails how |
|---|---|---|
| Instruction | `hardcoded_rules` in the registry | advisory — a confused model can ignore it |
| Capability | agent has no tool for the action | structural — `email_response_agent` cannot send |
| Database role | `003_agent_scopes.sql` GRANTs per agent | hard — `permission denied` |
| Row-level | RLS keyed on `app.agent_name` | fails **closed** when unset |
| Gate | `gate_agent`, runs first, zero data access | decision, never retried |
| Audit | `ops.audit_log`, `ops.failure_log`, `ops.hitl_queue` | detective, after the fact |

Layers 3 and 4 are what make the design defensible. Everything above them is
advice to a probabilistic system.

## Least privilege in practice

Each agent's `data_scope` in `AGENT_REGISTRY.yaml` maps 1:1 to a Postgres role
that holds those SELECTs and nothing else. Two deliberate cases worth naming:

- **`gate_agent` has zero data access.** It decides whether work may proceed. If
  it could read the data it is gating, the gate is theater.
- **`agent_order_tracking` cannot `SELECT core.entity`.** It answers one question
  about one order. Golden case `SCP-501` probes for `permission denied`; if that
  case passes, the scope is enforced rather than described.

RLS uses `current_setting('app.agent_name', true)`, which returns NULL when
unset. A NULL never matches the policy predicate, so an agent invoked without
identity sees zero rows. Failing closed is the design, not a side effect.

## Secrets

- `SUPABASE_SERVICE_ROLE_KEY` bypasses RLS entirely. It never enters a sub-agent
  process. Sub-agents connect as their own role or not at all.
- `guard_secrets.py` scans for Anthropic/OpenAI/AWS/GitHub key shapes, Supabase
  JWTs, and Postgres URLs with inline passwords on every Write/Edit.
- `ops.failure_log` stores `inputs_hash`, never the inputs.
- `.claude/settings.json` denies `Read(./.env)` and `Bash(curl:*)` — the latter
  because exfiltration in an agent repo is a one-line mistake.

## Data handling

- Synthetic data only unless the interviewer supplies real data. If they do, ask
  before it touches an external service, and say so out loud.
- `BLK-002` blocks health, biometric, precise geolocation, government ID, and
  full payment card data outright.
- Nothing leaves the machine that the interviewer did not put on it.

## The threat you should name unprompted

A prompt-injected source record telling an agent to ignore its instructions. The
answer here is not a better prompt — it is that the compromised agent still
cannot read outside its GRANTs, still cannot write outside `ops.*`, still cannot
send an email it has no tool for, and its output still goes through
`red_team_agent`, which must re-derive the claim from source rather than trust it.

Defense in depth is the point. Any single layer will eventually be talked past.
