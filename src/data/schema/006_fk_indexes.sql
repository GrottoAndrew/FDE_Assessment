-- =============================================================================
-- 006_fk_indexes.sql — index every foreign key.
--
-- Found by running scripts/db_report.sql against the live instance: 19 foreign
-- keys had no supporting index. Postgres indexes the REFERENCED side (it is a
-- primary key) but never the referencing side. The cost is invisible on an empty
-- database and shows up as a sequential scan on every join once quote_snapshot
-- has a few million rows — which it will, at one row per fetch.
--
-- Low-cardinality ISO code columns are indexed too: they are the join path from
-- a security to its currency and country, and they are cheap.
-- =============================================================================

CREATE INDEX IF NOT EXISTS account_entity_id_idx           ON core.account (entity_id);
CREATE INDEX IF NOT EXISTS account_country_code_idx        ON core.account (country_code);
CREATE INDEX IF NOT EXISTS account_currency_code_idx       ON core.account (currency_code);
CREATE INDEX IF NOT EXISTS contact_entity_id_idx           ON core.contact (entity_id);
CREATE INDEX IF NOT EXISTS contact_language_code_idx       ON core.contact (language_code);
CREATE INDEX IF NOT EXISTS contact_subdivision_code_idx    ON core.contact (subdivision_code);
CREATE INDEX IF NOT EXISTS entity_country_code_idx         ON core.entity (country_code);
CREATE INDEX IF NOT EXISTS entity_language_code_idx        ON core.entity (language_code);
CREATE INDEX IF NOT EXISTS entity_merged_into_idx          ON core.entity (merged_into) WHERE merged_into IS NOT NULL;
CREATE INDEX IF NOT EXISTS entity_xref_entity_id_idx       ON core.entity_xref (entity_id);
CREATE INDEX IF NOT EXISTS quote_currency_code_idx         ON md.quote_snapshot (currency_code);
CREATE INDEX IF NOT EXISTS security_entity_id_idx          ON md.security (entity_id);
CREATE INDEX IF NOT EXISTS security_country_code_idx       ON md.security (country_code);
CREATE INDEX IF NOT EXISTS security_currency_code_idx      ON md.security (currency_code);
CREATE INDEX IF NOT EXISTS security_cik_idx                ON md.security (cik);
CREATE INDEX IF NOT EXISTS candidate_link_figi_idx         ON news.candidate_link (figi);
CREATE INDEX IF NOT EXISTS headline_source_id_idx          ON news.headline (source_id);
CREATE INDEX IF NOT EXISTS flag_entity_id_idx              ON ops.flag (entity_id);
CREATE INDEX IF NOT EXISTS position_entity_id_idx          ON pos.position_snapshot (entity_id);
CREATE INDEX IF NOT EXISTS position_figi_idx               ON pos.position_snapshot (figi);
CREATE INDEX IF NOT EXISTS position_currency_code_idx      ON pos.position_snapshot (currency_code);
CREATE INDEX IF NOT EXISTS synonym_entity_id_idx           ON core.entity_synonym (entity_id);

-- The desk's hottest read: latest quote for one security. Already covered by
-- quote_latest (figi, as_of_at_utc DESC) from 004; named here so the next person
-- does not add a duplicate.
