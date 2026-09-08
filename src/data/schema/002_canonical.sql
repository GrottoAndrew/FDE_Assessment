-- =============================================================================
-- 002_canonical.sql
-- The canonical layer. One row per real-world thing, one surrogate key, and an
-- xref table that maps every source system's id onto it.
--
-- WHY THIS SHAPE: agents disagree when they read different source systems and
-- each believes it holds "the" record. Making core.entity the only thing an
-- agent may join to turns "which system is right?" from an argument into a
-- query against core.entity_xref. discrepancy_agent exists to walk this table.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS ops;
CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "citext";     -- case-insensitive email

-- ---------------------------------------------------------------------------
-- CANONICAL ENTITY — the join target for everything
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS core.entity (
    entity_id     uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type   text        NOT NULL CHECK (entity_type IN ('person','organization','asset')),
    display_name  text        NOT NULL,
    country_code  char(2)     REFERENCES iso.country(code),
    language_code char(2)     REFERENCES iso.language(code),
    is_canonical  boolean     NOT NULL DEFAULT true,
    merged_into   uuid        REFERENCES core.entity(entity_id),   -- set when deduped
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    -- a merged entity is no longer canonical; enforce the pair, don't trust callers
    CONSTRAINT merge_consistency CHECK (
        (merged_into IS NULL AND is_canonical) OR (merged_into IS NOT NULL AND NOT is_canonical)
    )
);

-- ---------------------------------------------------------------------------
-- CROSS-REFERENCE — every source id resolves here. This IS the canonical join.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS core.entity_xref (
    xref_id       bigserial   PRIMARY KEY,
    entity_id     uuid        NOT NULL REFERENCES core.entity(entity_id) ON DELETE CASCADE,
    source_system text        NOT NULL,          -- 'crm','billing','support',...
    source_id     text        NOT NULL,
    match_method  text        NOT NULL CHECK (match_method IN ('exact','deterministic','fuzzy','manual')),
    match_score   numeric(4,3) CHECK (match_score BETWEEN 0 AND 1),
    ingested_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_system, source_id)            -- one source id maps to exactly one entity
);
CREATE INDEX IF NOT EXISTS idx_xref_entity ON core.entity_xref(entity_id);

-- Fuzzy matches are provisional: they must be reviewed, not trusted.
CREATE INDEX IF NOT EXISTS idx_xref_fuzzy_review
    ON core.entity_xref(entity_id) WHERE match_method = 'fuzzy' AND match_score < 0.90;

CREATE TABLE IF NOT EXISTS core.account (
    account_id   uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id    uuid        NOT NULL REFERENCES core.entity(entity_id),
    tier         text        NOT NULL DEFAULT 'standard' CHECK (tier IN ('standard','growth','strategic')),
    currency_code char(3)    NOT NULL REFERENCES iso.currency(code),
    country_code char(2)     NOT NULL REFERENCES iso.country(code),
    opened_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS core.contact (
    contact_id   uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id    uuid        NOT NULL REFERENCES core.entity(entity_id),
    email        citext,
    subdivision_code text    REFERENCES iso.subdivision(code),
    timezone     text,                            -- IANA; null => appointment agent escalates
    language_code char(2)    REFERENCES iso.language(code)
);

-- Conformed date dimension: every time-series metric joins here so that
-- "last quarter" means one thing across every agent.
CREATE TABLE IF NOT EXISTS core.dim_date (
    date_key    date    PRIMARY KEY,
    iso_year    int     NOT NULL,                 -- ISO-8601 week-numbering year
    iso_week    int     NOT NULL,                 -- ISO-8601 week 1..53
    iso_dow     int     NOT NULL,                 -- ISO-8601 day of week 1=Mon
    month       int     NOT NULL,
    quarter     int     NOT NULL,
    is_weekend  boolean NOT NULL
);

-- ---------------------------------------------------------------------------
-- MONEY: never a bare number. Amount and its ISO-4217 code travel together.
-- ---------------------------------------------------------------------------
-- ONE money representation, everywhere. Chosen so the store, the API, and the
-- UI hold the same value with no translation step (ADR-0007).
--   * numeric, never float: floats do not represent money.
--   * scale 6: SEC Rule 612 quotes sub-$1 securities in $0.0001 increments, so
--     a 2-decimal minor-unit integer cannot hold a lawful bid. 6 leaves room
--     for FX and per-share averages without a second type.
--   * every amount still travels with its ISO-4217 code. A bare number is a defect.
--   * serialize as a JSON *string*, not a JSON number — IEEE-754 loses the tail.
CREATE DOMAIN core.money AS numeric(20,6);

-- Rule 612 minimum pricing increments. Applies to QUOTATIONS (bid/ask), not to
-- executions: a trade may print sub-penny through price improvement, a quote
-- may not. Enforced on md.quote_snapshot's bid/ask in 004_domain.sql.
CREATE OR REPLACE FUNCTION core.is_rule612_increment(px numeric)
RETURNS boolean AS $$
    SELECT CASE
        WHEN px IS NULL      THEN true
        WHEN px <= 0         THEN false
        WHEN px < 1.00       THEN (px * 10000) = trunc(px * 10000)   -- $0.0001
        ELSE                      (px * 100)   = trunc(px * 100)     -- $0.01
    END;
$$ LANGUAGE sql IMMUTABLE;
COMMENT ON FUNCTION core.is_rule612_increment(numeric) IS
  'SEC Rule 612 quotation increments as originally adopted. The 2024 tick-size '
  'amendments add a $0.005 increment for tick-constrained NMS stocks; confirm '
  'the operative compliance date before relaxing this (RISK: A10).';

-- ---------------------------------------------------------------------------
-- OPS: the tables that make guardrails observable
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ops.hitl_queue (
    hitl_id      bigserial   PRIMARY KEY,
    run_id       uuid        NOT NULL,
    agent_name   text        NOT NULL,
    severity     text        NOT NULL CHECK (severity IN
                    ('gate_block','gate_ask','indeterminate','conflict','retry_exhausted','low_confidence')),
    question     text,
    payload      jsonb       NOT NULL DEFAULT '{}'::jsonb,
    status       text        NOT NULL DEFAULT 'open' CHECK (status IN ('open','answered','dismissed')),
    resolution   text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    resolved_at  timestamptz
);
CREATE INDEX IF NOT EXISTS idx_hitl_open ON ops.hitl_queue(created_at) WHERE status = 'open';

CREATE TABLE IF NOT EXISTS ops.audit_log (
    audit_id     bigserial   PRIMARY KEY,
    run_id       uuid        NOT NULL,
    agent_name   text        NOT NULL,
    action       text        NOT NULL,
    rule_id      text,                            -- set when a heuristic overrode a decision
    before_state jsonb,
    after_state  jsonb,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_overrides ON ops.audit_log(rule_id) WHERE rule_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS ops.failure_log (
    failure_id   bigserial   PRIMARY KEY,
    run_id       uuid        NOT NULL,
    agent_name   text        NOT NULL,
    step         text,
    attempts     int         NOT NULL,
    last_error   text        NOT NULL,
    inputs_hash  text        NOT NULL,            -- hash, not payload: no PII in logs
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- Cross-domain handoff. A sales orchestrator that notices marketing work drops
-- it here and forgets it. This is what keeps the silos actually siloed.
CREATE TABLE IF NOT EXISTS ops.handoff_queue (
    handoff_id     bigserial   PRIMARY KEY,
    run_id         uuid        NOT NULL,
    from_domain    text        NOT NULL,
    target_domain  text        NOT NULL,
    observation    text        NOT NULL,
    payload        jsonb       NOT NULL DEFAULT '{}'::jsonb,
    status         text        NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending','claimed','done')),
    created_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT no_self_handoff CHECK (from_domain <> target_domain)
);

CREATE TABLE IF NOT EXISTS ops.flag (
    flag_id     bigserial   PRIMARY KEY,
    entity_id   uuid        REFERENCES core.entity(entity_id),
    agent_name  text        NOT NULL,
    flag_type   text        NOT NULL,
    detail      text,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- THE CANONICAL JOIN — agents query this view, never raw source tables.
-- Excludes merged duplicates by construction, so no agent can resurrect one.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW core.v_entity_resolved AS
SELECT
    e.entity_id,
    e.entity_type,
    e.display_name,
    e.country_code,
    c.name              AS country_name,
    c.default_tz        AS country_default_tz,
    e.language_code,
    a.account_id,
    a.tier,
    a.currency_code,
    cur.minor_unit      AS currency_minor_unit,
    count(x.xref_id)    AS source_system_count,
    array_agg(DISTINCT x.source_system) FILTER (WHERE x.source_system IS NOT NULL) AS source_systems,
    bool_or(x.match_method = 'fuzzy' AND x.match_score < 0.90) AS has_provisional_match
FROM core.entity e
LEFT JOIN iso.country   c   ON c.code   = e.country_code
LEFT JOIN core.account  a   ON a.entity_id = e.entity_id
LEFT JOIN iso.currency  cur ON cur.code = a.currency_code
LEFT JOIN core.entity_xref x ON x.entity_id = e.entity_id
WHERE e.is_canonical
GROUP BY e.entity_id, e.entity_type, e.display_name, e.country_code,
         c.name, c.default_tz, e.language_code, a.account_id, a.tier,
         a.currency_code, cur.minor_unit;

COMMENT ON VIEW core.v_entity_resolved IS
  'Canonical read surface. has_provisional_match=true means a low-confidence '
  'fuzzy link exists: agents must escalate rather than assert on these rows.';
