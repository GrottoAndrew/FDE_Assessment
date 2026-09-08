# src/

| dir | holds | filled |
|---|---|---|
| `agents/` | `AGENT_REGISTRY.yaml` — the only place agents exist | ✅ pre-built |
| `policies/` | gating · heuristics · retry, as data not prompt text | ✅ pre-built |
| `data/schema/` | DDL, applied in numeric order | ✅ pre-built (001–003) |
| `data/synthetic/` | generated fixtures for the golden set | sprint day |
| `orchestrator/` | per-domain routing + the single commit point | sprint day |
| `common/` | db access, types, structured logging | sprint day |

`004_domain.sql` — the problem's own tables — is written at T-10, after the
entity map in `docs/build_plans/BUILD_PLAN_TEMPLATE.md` is filled in.
