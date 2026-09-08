-- =============================================================================
-- 004_domain.sql — advisor quote-and-disclosure desk (US equities)
--
-- Apply after 001, 002. Then re-apply 003 so the domain agent roles land.
-- Local Postgres only. No Supabase (sprint scope decision, 2026-09-08).
--
-- Design rules in force here:
--   * one money type: core.money (numeric(20,6)) + an ISO-4217 code. No translation.
--   * quotations obey Rule 612 increments; executions do not have to.
--   * every externally-sourced row carries source, as_of_at_utc, retrieved_at_utc
--     and delay_seconds. A price without provenance is a defect, not a value.
--   * bad data is stored and flagged, never rejected and never repaired.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS md;      -- market data
CREATE SCHEMA IF NOT EXISTS pos;     -- positions, from Orion
CREATE SCHEMA IF NOT EXISTS edgar;   -- SEC filings
CREATE SCHEMA IF NOT EXISTS news;    -- public/OSS headlines
CREATE SCHEMA IF NOT EXISTS wsp;     -- WSP rule seam (table only; logic deferred)

-- ---------------------------------------------------------------------------
-- SECURITY MASTER — FIGI is the key. A ticker is a label, not an identifier:
-- it is reused across issuers over time, so a ticker-keyed cache eventually
-- returns a dead company's price.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS md.security (
    figi              char(12)    PRIMARY KEY,
    ticker            text        NOT NULL,
    cik               char(10),                       -- EDGAR issuer, nullable: not every FIGI files
    entity_id         uuid        REFERENCES core.entity(entity_id),
    security_name     text        NOT NULL,
    primary_mic       char(4)     NOT NULL,           -- ISO-10383 market identifier
    currency_code     char(3)     NOT NULL REFERENCES iso.currency(code),
    country_code      char(2)     NOT NULL REFERENCES iso.country(code),
    is_active         boolean     NOT NULL DEFAULT true,
    first_seen_at_utc timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT security_us_only_for_now CHECK (country_code = 'US')
);
CREATE UNIQUE INDEX IF NOT EXISTS security_active_ticker
    ON md.security (ticker) WHERE is_active;
COMMENT ON CONSTRAINT security_us_only_for_now ON md.security IS
  'Scope guard, not a modeling limit. ADRs/ISO columns already carry non-US and '
  'ADR instruments; drop this CHECK when that scope opens.';

-- ---------------------------------------------------------------------------
-- QUOTE SNAPSHOT — one row per fetch. Immutable; never updated in place, so the
-- history of what the desk was shown survives.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS md.quote_snapshot (
    quote_id          bigserial   PRIMARY KEY,
    figi              char(12)    NOT NULL REFERENCES md.security(figi),
    bid               core.money,
    ask               core.money,
    bid_size          integer,
    ask_size          integer,
    last              core.money,
    prev_close        core.money,
    currency_code     char(3)     NOT NULL REFERENCES iso.currency(code),
    source            text        NOT NULL,           -- 'yahoo' | 'orion' | entitled feed later
    delay_seconds     integer     NOT NULL,           -- 0 only when entitled real-time
    as_of_at_utc      timestamptz NOT NULL,           -- when the venue said this was true
    retrieved_at_utc  timestamptz NOT NULL DEFAULT now(),
    session           text        NOT NULL CHECK (session IN ('pre','regular','post','closed')),
    is_halted         boolean     NOT NULL DEFAULT false,
    CONSTRAINT quote_bid_on_rule612  CHECK (core.is_rule612_increment(bid)),
    CONSTRAINT quote_ask_on_rule612  CHECK (core.is_rule612_increment(ask)),
    CONSTRAINT quote_sizes_nonneg    CHECK (COALESCE(bid_size,0) >= 0 AND COALESCE(ask_size,0) >= 0)
);
-- Deliberately NO check that bid <= ask. Locked and crossed markets are real.
-- The condition is surfaced, not suppressed: quote_snapshot_agent returns
-- INDETERMINATE on a crossed book rather than inventing a mid.
ALTER TABLE md.quote_snapshot
    ADD COLUMN IF NOT EXISTS is_crossed boolean
    GENERATED ALWAYS AS (bid IS NOT NULL AND ask IS NOT NULL AND bid > ask) STORED;
CREATE INDEX IF NOT EXISTS quote_latest ON md.quote_snapshot (figi, as_of_at_utc DESC);

CREATE OR REPLACE VIEW md.v_quote_latest AS
SELECT DISTINCT ON (q.figi)
    q.figi, s.ticker, q.bid, q.ask, q.last, q.prev_close, q.currency_code,
    q.bid_size, q.ask_size, q.source, q.delay_seconds, q.as_of_at_utc,
    q.retrieved_at_utc, q.session, q.is_halted, q.is_crossed,
    (q.ask - q.bid)                                             AS spread_abs,
    CASE WHEN q.bid > 0 AND q.ask > 0 AND q.ask >= q.bid
         THEN round(((q.ask - q.bid) / ((q.ask + q.bid) / 2)) * 10000, 2)
    END                                                          AS spread_bps,
    CASE WHEN q.bid > 0 AND q.ask > 0 AND q.ask >= q.bid
         THEN (q.ask + q.bid) / 2
    END                                                          AS mid
FROM md.quote_snapshot q
JOIN md.security s ON s.figi = q.figi
ORDER BY q.figi, q.as_of_at_utc DESC, q.quote_id DESC;
COMMENT ON VIEW md.v_quote_latest IS
  'spread_bps and mid are NULL on a crossed or one-sided book by construction. '
  'A NULL here means "undefined", and the agent must say so rather than compute one.';

-- ---------------------------------------------------------------------------
-- CALL BUDGET — the free-tier quote source has a hard monthly cap. Spending it
-- is a fact to be recorded, not a limit to be discovered at 09:31.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS md.quote_call_budget (
    source          text    NOT NULL,
    period_month    date    NOT NULL,        -- first day of the month, UTC
    calls_used      integer NOT NULL DEFAULT 0 CHECK (calls_used >= 0),
    calls_limit     integer NOT NULL CHECK (calls_limit > 0),
    PRIMARY KEY (source, period_month)
);

-- ---------------------------------------------------------------------------
-- POSITIONS — Orion, reconciled through the prior close. quantity carries its
-- own as_of because T-1 quantity x live price is wrong after any intraday trade.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pos.position_snapshot (
    position_id        bigserial   PRIMARY KEY,
    orion_account_id   text        NOT NULL,
    entity_id          uuid        REFERENCES core.entity(entity_id),
    figi               char(12)    NOT NULL REFERENCES md.security(figi),
    quantity           numeric(28,8) NOT NULL,
    cost_basis         core.money,
    currency_code      char(3)     NOT NULL REFERENCES iso.currency(code),
    close_price        core.money,                    -- Orion's reconciled prior close
    as_of_date         date        NOT NULL,          -- the reconciliation date, not "today"
    source             text        NOT NULL DEFAULT 'orion',
    retrieved_at_utc   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (orion_account_id, figi, as_of_date)
);
COMMENT ON COLUMN pos.position_snapshot.as_of_date IS
  'Reconciliation date. Any notional combining this quantity with a live price '
  'must be labeled as-of this date or escalated. See RISK A3 / gap G-08.';

-- ---------------------------------------------------------------------------
-- EDGAR — accession_no is the citation key for every disclosure claim.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS edgar.filing (
    accession_no      char(20)    PRIMARY KEY,
    cik               char(10)    NOT NULL,
    form_type         text        NOT NULL,
    filed_at_utc      timestamptz NOT NULL,
    period_of_report  date,
    primary_doc_url   text        NOT NULL,
    retrieved_at_utc  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS filing_by_cik ON edgar.filing (cik, filed_at_utc DESC);

CREATE TABLE IF NOT EXISTS edgar.xbrl_fact (
    fact_id        bigserial   PRIMARY KEY,
    accession_no   char(20)    NOT NULL REFERENCES edgar.filing(accession_no),
    cik            char(10)    NOT NULL,
    tag            text        NOT NULL,          -- us-gaap taxonomy tag
    value_num      numeric,
    value_text     text,
    unit           text,                          -- 'USD', 'shares', ...
    period_start   date,
    period_end     date,
    UNIQUE (accession_no, tag, period_start, period_end)
);
COMMENT ON TABLE edgar.xbrl_fact IS
  'Tagged facts only. An untagged number extracted from prose is a model output, '
  'not a disclosure — filing_fact_agent returns INDETERMINATE instead.';

-- ---------------------------------------------------------------------------
-- NEWS — public sources. A headline is evidence of a claim being published,
-- never evidence that it caused a price move.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS news.source (
    source_id     bigserial PRIMARY KEY,
    domain        text      NOT NULL UNIQUE,
    display_name  text      NOT NULL,
    is_allowed    boolean   NOT NULL DEFAULT false,
    added_by      text      NOT NULL
);

CREATE TABLE IF NOT EXISTS news.headline (
    headline_id       bigserial   PRIMARY KEY,
    source_id         bigint      NOT NULL REFERENCES news.source(source_id),
    url               text        NOT NULL UNIQUE,
    title             text        NOT NULL,
    snippet           text,
    published_at_utc  timestamptz,
    retrieved_at_utc  timestamptz NOT NULL DEFAULT now(),
    query_term        text        NOT NULL
);

-- A candidate link, never an asserted cause. Ranking/relevancy is explicitly
-- out of scope for this prototype; this table is where that model attaches.
CREATE TABLE IF NOT EXISTS news.candidate_link (
    link_id       bigserial   PRIMARY KEY,
    headline_id   bigint      NOT NULL REFERENCES news.headline(headline_id),
    figi          char(12)    NOT NULL REFERENCES md.security(figi),
    basis         text        NOT NULL CHECK (basis IN
                     ('issuer_named','ticker_named','sector_named','geography_named','supply_chain_named')),
    asserted      boolean     NOT NULL DEFAULT false CHECK (asserted = false),
    UNIQUE (headline_id, figi, basis)
);
COMMENT ON CONSTRAINT candidate_link_asserted_check ON news.candidate_link IS
  'asserted is pinned false by CHECK. Nothing in this prototype may promote a '
  'candidate link to a stated cause. Removing this CHECK is a design change '
  'requiring the relevancy/reranking model that is out of scope here.';

-- ---------------------------------------------------------------------------
-- COMPLIANCE SEAM — table exists so flags have a referent and a join key.
-- Reg BI / FINRA 2210 logic is OUT OF SCOPE this sprint (sponsor decision).
-- Building the seam now avoids a migration when the compliance suite lands.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS wsp.rule (
    wsp_rule_id    text    PRIMARY KEY,
    title          text    NOT NULL,
    source_section text,
    is_active      boolean NOT NULL DEFAULT false,
    owner          text    NOT NULL
);
COMMENT ON TABLE wsp.rule IS
  'Empty by design this sprint. is_active defaults false so nothing can fire '
  'against an unreviewed rule set.';

CREATE TABLE IF NOT EXISTS ops.advisor_interaction (
    interaction_id  bigserial   PRIMARY KEY,
    run_id          uuid        NOT NULL,
    advisor_id      text        NOT NULL,
    channel         text        NOT NULL DEFAULT 'internal_chat'
                    CHECK (channel IN ('internal_chat')),   -- internal only; no client-facing channel exists
    request_text    text        NOT NULL,
    asked_at_utc    timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE ops.advisor_interaction IS
  'The join key every compliance flag attaches to. The channel CHECK is the '
  'structural reason this system is not a customer-facing communication surface.';
