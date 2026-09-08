-- =============================================================================
-- 003_agent_scopes.sql
-- Least privilege, enforced by the database rather than by prompt text.
--
-- A prompt that says "only read the order table" is a suggestion. A role that
-- cannot SELECT anything else is a guarantee. Each agent in AGENT_REGISTRY.yaml
-- gets a DB role granted exactly its declared data_scope, and nothing else.
--
-- This is the control that makes "narrow sub-agent" a real boundary. It is also
-- the slide-4 talking point: the blast radius of a compromised or confused
-- agent is bounded by its GRANTs, not by its instructions.
-- =============================================================================

-- Baseline: no ambient access anywhere.
REVOKE ALL ON ALL TABLES IN SCHEMA core, ops, iso FROM PUBLIC;

-- Postgres has no CREATE ROLE IF NOT EXISTS; this is the idempotent equivalent.
CREATE OR REPLACE FUNCTION ops.ensure_role(rolename text) RETURNS void AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = rolename) THEN
        EXECUTE format('CREATE ROLE %I NOLOGIN', rolename);
    END IF;
END;
$$ LANGUAGE plpgsql;


-- Everyone may read the ISO vocabulary. It is public reference data and every
-- agent needs it to normalize. Nobody may write it.
SELECT ops.ensure_role('agent_base');
GRANT USAGE ON SCHEMA iso TO agent_base;
GRANT SELECT ON ALL TABLES IN SCHEMA iso TO agent_base;

-- --- gate_agent: decides without looking. Zero data access by design. --------
SELECT ops.ensure_role('agent_gate');
GRANT USAGE ON SCHEMA ops TO agent_gate;
GRANT INSERT ON ops.hitl_queue TO agent_gate;
-- deliberately NO grant on core.* and NO inheritance from agent_base

-- --- red_team_agent: reads everything canonical, writes nothing -------------
SELECT ops.ensure_role('agent_red_team');
GRANT agent_base TO agent_red_team;
GRANT USAGE ON SCHEMA core TO agent_red_team;
GRANT SELECT ON ALL TABLES IN SCHEMA core TO agent_red_team;

-- --- discrepancy_agent: needs the xref table; that is the whole job ---------
SELECT ops.ensure_role('agent_discrepancy');
GRANT agent_base TO agent_discrepancy;
GRANT USAGE ON SCHEMA core TO agent_discrepancy;
GRANT SELECT ON core.entity, core.entity_xref, core.v_entity_resolved TO agent_discrepancy;

-- --- heuristic_override_agent: reads the decision context, writes the audit --
SELECT ops.ensure_role('agent_heuristic');
GRANT agent_base TO agent_heuristic;
GRANT USAGE ON SCHEMA core, ops TO agent_heuristic;
GRANT SELECT ON core.entity, core.account, core.v_entity_resolved TO agent_heuristic;
GRANT INSERT ON ops.audit_log, ops.hitl_queue TO agent_heuristic;

-- --- DOMAIN AGENTS (illustrative; regenerate from the registry) -------------
-- Pattern: SELECT only on the tables in data_scope; INSERT only on write_scope.

SELECT ops.ensure_role('agent_order_tracking');
GRANT agent_base TO agent_order_tracking;
GRANT USAGE ON SCHEMA sales TO agent_order_tracking;
GRANT SELECT ON sales.order, sales.shipment TO agent_order_tracking;
-- no core.*, no ops.*, no writes: it answers one question about one order

SELECT ops.ensure_role('agent_email_response');
GRANT agent_base TO agent_email_response;
GRANT USAGE ON SCHEMA core, sales TO agent_email_response;
GRANT SELECT ON core.contact, sales.activity TO agent_email_response;
-- no INSERT anywhere: this agent structurally cannot send. A human sends.

-- --- Row-level security: scope agents to the rows, not just the tables ------
ALTER TABLE core.entity        ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.entity_xref   ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.hitl_queue     ENABLE ROW LEVEL SECURITY;

-- Merged duplicates are invisible to agents. They cannot cite a stale record
-- even by guessing its id.
CREATE POLICY entity_canonical_only ON core.entity
    FOR SELECT TO agent_base
    USING (is_canonical);

-- An agent sees only the HITL rows it raised.
CREATE POLICY hitl_own_rows ON ops.hitl_queue
    FOR SELECT TO agent_base
    USING (agent_name = current_setting('app.agent_name', true));

-- Runtime sets this per invocation:  SET LOCAL app.agent_name = 'order_tracking_agent';
-- Unset => current_setting returns NULL => the policy matches nothing => the
-- agent sees no rows. Failing closed is the point.

-- =============================================================================
-- VERIFY (run after applying; each should return zero rows)
-- =============================================================================
-- Any agent role holding a grant outside its declared scope:
--   SELECT grantee, table_schema, table_name, privilege_type
--   FROM information_schema.role_table_grants
--   WHERE grantee LIKE 'agent_%' ORDER BY grantee, table_schema, table_name;
--
-- Any table an agent can write that is not an ops.* sink:
--   SELECT grantee, table_schema, table_name FROM information_schema.role_table_grants
--   WHERE grantee LIKE 'agent_%' AND privilege_type IN ('INSERT','UPDATE','DELETE')
--     AND table_schema <> 'ops';
