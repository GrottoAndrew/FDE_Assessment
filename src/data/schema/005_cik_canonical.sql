-- =============================================================================
-- 005_cik_canonical.sql — canonical ids become natural keys; CIK identifies a
-- company. Adds the name-synonym join and the split-out security/price view.
--
-- Apply after 004. Safe on an empty database; on a populated one it rewrites
-- entity_id in six tables and must be run inside a maintenance window.
--
-- WHY A NATURAL KEY: gen_random_uuid() means the same company ingested twice is
-- two entities with no way to tell from the id alone. A CIK is assigned by the
-- SEC, is stable for the life of the filer, and is the join key EDGAR already
-- uses. The id stops being an opaque number and starts being an assertion the
-- database can check.
--
-- WHAT CIK CANNOT DO: it identifies an ISSUER, not a security and not a client.
--   * one CIK, many securities  -> securities stay keyed on FIGI
--   * accounts and contacts have no CIK -> prefixed keys, checked by entity_type
-- So entity_id is uniform in TYPE (text, checked by shape) rather than uniform
-- in scheme. Forcing one scheme on all three would mean inventing CIKs for
-- households, which is a fabricated identifier in the canonical table.
-- =============================================================================

BEGIN;

-- Every view over a column whose type is changing must be dropped first, and a
-- re-run of this file hits views that the file itself created. Idempotency is
-- not a nicety here: a migration you cannot run twice is a migration you cannot
-- safely resume after it fails halfway.
DROP VIEW IF EXISTS md.v_security_price;
DROP VIEW IF EXISTS core.v_synonym_collision;
DROP VIEW IF EXISTS core.v_entity_resolved;

-- --- entity_id: uuid -> text -------------------------------------------------
ALTER TABLE core.entity_xref      DROP CONSTRAINT IF EXISTS entity_xref_entity_id_fkey;
ALTER TABLE core.account          DROP CONSTRAINT IF EXISTS account_entity_id_fkey;
ALTER TABLE core.contact          DROP CONSTRAINT IF EXISTS contact_entity_id_fkey;
ALTER TABLE md.security           DROP CONSTRAINT IF EXISTS security_entity_id_fkey;
ALTER TABLE pos.position_snapshot DROP CONSTRAINT IF EXISTS position_snapshot_entity_id_fkey;
ALTER TABLE ops.flag              DROP CONSTRAINT IF EXISTS flag_entity_id_fkey;
ALTER TABLE core.entity           DROP CONSTRAINT IF EXISTS entity_merged_into_fkey;
-- ops.flag was found by applying this against a live instance, not by reading
-- the DDL. Enumerate dependents with pg_constraint before a type change:
--   SELECT conrelid::regclass, conname FROM pg_constraint
--   WHERE confrelid = 'core.entity'::regclass AND contype = 'f';

ALTER TABLE core.entity
    ALTER COLUMN entity_id  DROP DEFAULT,
    ALTER COLUMN entity_id  TYPE text USING entity_id::text,
    ALTER COLUMN merged_into TYPE text USING merged_into::text;
ALTER TABLE core.entity_xref      ALTER COLUMN entity_id TYPE text USING entity_id::text;
ALTER TABLE core.account          ALTER COLUMN entity_id TYPE text USING entity_id::text;
ALTER TABLE core.contact          ALTER COLUMN entity_id TYPE text USING entity_id::text;
ALTER TABLE md.security           ALTER COLUMN entity_id TYPE text USING entity_id::text;
ALTER TABLE pos.position_snapshot ALTER COLUMN entity_id TYPE text USING entity_id::text;
ALTER TABLE ops.flag              ALTER COLUMN entity_id TYPE text USING entity_id::text;

-- 'issuer' is its own type: an SEC filer is not interchangeable with a vendor
-- organization, and only an issuer can carry a CIK.
ALTER TABLE core.entity DROP CONSTRAINT IF EXISTS entity_entity_type_check;
ALTER TABLE core.entity ADD  CONSTRAINT entity_entity_type_check
    CHECK (entity_type IN ('issuer','person','organization','asset'));

-- The id must match its type. This is the whole point of the natural key: an
-- issuer whose id is not a 10-digit CIK cannot be inserted at all.
ALTER TABLE core.entity DROP CONSTRAINT IF EXISTS entity_id_shape;
ALTER TABLE core.entity ADD CONSTRAINT entity_id_shape CHECK (
    CASE entity_type
        WHEN 'issuer'       THEN entity_id ~ '^[0-9]{10}$'
        WHEN 'person'       THEN entity_id ~ '^PER-[0-9A-Za-z_-]{4,}$'
        WHEN 'organization' THEN entity_id ~ '^ORG-[0-9A-Za-z_-]{4,}$'
        WHEN 'asset'        THEN entity_id ~ '^AST-[0-9A-Za-z_-]{4,}$'
    END
);
COMMENT ON CONSTRAINT entity_id_shape ON core.entity IS
  'A canonical id you cannot read is a canonical id you cannot audit. Issuers '
  'use the SEC CIK, zero-padded to 10. Everything else carries a type prefix.';

ALTER TABLE core.entity           ADD CONSTRAINT entity_merged_into_fkey
    FOREIGN KEY (merged_into) REFERENCES core.entity(entity_id);
ALTER TABLE core.entity_xref      ADD CONSTRAINT entity_xref_entity_id_fkey
    FOREIGN KEY (entity_id) REFERENCES core.entity(entity_id) ON DELETE CASCADE;
ALTER TABLE core.account          ADD CONSTRAINT account_entity_id_fkey
    FOREIGN KEY (entity_id) REFERENCES core.entity(entity_id);
ALTER TABLE core.contact          ADD CONSTRAINT contact_entity_id_fkey
    FOREIGN KEY (entity_id) REFERENCES core.entity(entity_id);
ALTER TABLE md.security           ADD CONSTRAINT security_entity_id_fkey
    FOREIGN KEY (entity_id) REFERENCES core.entity(entity_id);
ALTER TABLE pos.position_snapshot ADD CONSTRAINT position_snapshot_entity_id_fkey
    FOREIGN KEY (entity_id) REFERENCES core.entity(entity_id);
ALTER TABLE ops.flag              ADD CONSTRAINT flag_entity_id_fkey
    FOREIGN KEY (entity_id) REFERENCES core.entity(entity_id);

-- md.security.cik and core.entity.entity_id are now the same key for issuers.
-- Two columns holding one identity is exactly how they drift, so tie them.
ALTER TABLE md.security DROP CONSTRAINT IF EXISTS security_cik_matches_entity;
ALTER TABLE md.security ADD CONSTRAINT security_cik_matches_entity CHECK (
    cik IS NULL OR entity_id IS NULL OR cik = entity_id
);

CREATE OR REPLACE VIEW core.v_entity_resolved AS
SELECT
    e.entity_id, e.entity_type, e.display_name, e.country_code,
    c.name AS country_name, c.default_tz AS country_default_tz, e.language_code,
    a.account_id, a.tier, a.currency_code, cur.minor_unit AS currency_minor_unit,
    count(x.xref_id) AS source_system_count,
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

-- --- Name synonyms -----------------------------------------------------------
-- One row per way a human might write a company's name. Kept OUT of core.entity
-- so display_name stays the single canonical label and the alternatives stay
-- auditable: every synonym has a kind, a source, and a confidence.
CREATE TABLE IF NOT EXISTS core.entity_synonym (
    synonym_id   bigserial PRIMARY KEY,
    entity_id    text      NOT NULL REFERENCES core.entity(entity_id) ON DELETE CASCADE,
    synonym      text      NOT NULL,
    synonym_norm text      GENERATED ALWAYS AS (lower(regexp_replace(synonym, '[^a-zA-Z0-9]', '', 'g'))) STORED,
    kind         text      NOT NULL CHECK (kind IN
                   ('legal_name','former_name','dba','short_name','ticker',
                    'exchange_qualified_ticker','misspelling','phonetic','transliteration')),
    confidence   numeric(4,3) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    source       text      NOT NULL,
    added_at_utc timestamptz NOT NULL DEFAULT now(),
    UNIQUE (entity_id, synonym, kind)
);
CREATE INDEX IF NOT EXISTS entity_synonym_norm ON core.entity_synonym (synonym_norm);

COMMENT ON TABLE core.entity_synonym IS
  'A resolution AID, not an assertion. A match here below 0.90 confidence is a '
  'provisional match: the agent must surface the resolution it used rather than '
  'silently answering about a company the advisor did not name.';
COMMENT ON COLUMN core.entity_synonym.synonym_norm IS
  'Case- and punctuation-folded form. "NVIDIA Corp." and "nvidia corp" collapse '
  'to one key so the lookup does not depend on how someone typed it.';

-- Collision guard. A synonym that resolves to two canonical entities is worse
-- than no synonym: it makes a wrong answer look resolved. Ambiguity must be
-- visible to the resolver, so it is a view rather than a constraint.
CREATE OR REPLACE VIEW core.v_synonym_collision AS
SELECT synonym_norm, count(DISTINCT entity_id) AS entity_count,
       array_agg(DISTINCT entity_id) AS entity_ids
FROM core.entity_synonym
GROUP BY synonym_norm
HAVING count(DISTINCT entity_id) > 1;

-- --- Split-out read surface: symbol · name · price ---------------------------
CREATE OR REPLACE VIEW md.v_security_price AS
SELECT
    s.figi,
    s.ticker                AS symbol,
    s.security_name         AS name,
    e.display_name          AS issuer_name,
    s.cik,
    q.last                  AS price,
    q.prev_close,
    q.bid,
    q.ask,
    q.currency_code,
    q.source                AS price_source,
    q.delay_seconds,
    q.as_of_at_utc          AS price_as_of_at_utc,
    q.session,
    q.is_crossed,
    q.is_halted
FROM md.security s
LEFT JOIN core.entity e ON e.entity_id = s.entity_id
LEFT JOIN LATERAL (
    SELECT * FROM md.quote_snapshot qq
    WHERE qq.figi = s.figi
    ORDER BY qq.as_of_at_utc DESC, qq.quote_id DESC
    LIMIT 1
) q ON true
WHERE s.is_active;
COMMENT ON VIEW md.v_security_price IS
  'symbol / name / price split out for the desk. price is NULL when no snapshot '
  'exists — NULL means "not fetched", and an agent must say that rather than '
  'fall back to prev_close.';

-- --- Deterministic resolver: the tier-0 path an agent uses --------------------
-- No model. A lookup that returns its confidence and its provenance, so the
-- caller can decide, rather than a fuzzy match that decides for it.
CREATE OR REPLACE FUNCTION core.resolve_entity(raw text)
RETURNS TABLE (entity_id text, display_name text, matched_on text, kind text,
               confidence numeric, is_provisional boolean, is_ambiguous boolean)
AS $$
    WITH norm AS (SELECT lower(regexp_replace(raw, '[^a-zA-Z0-9]', '', 'g')) AS k),
    hits AS (
        SELECT s.entity_id, e.display_name, s.synonym AS matched_on, s.kind, s.confidence
        FROM core.entity_synonym s
        JOIN core.entity e ON e.entity_id = s.entity_id AND e.is_canonical
        WHERE s.synonym_norm = (SELECT k FROM norm)
        UNION
        SELECT e.entity_id, e.display_name, e.display_name, 'display_name', 1.000
        FROM core.entity e
        WHERE e.is_canonical
          AND lower(regexp_replace(e.display_name, '[^a-zA-Z0-9]', '', 'g')) = (SELECT k FROM norm)
    )
    SELECT h.entity_id, h.display_name, h.matched_on, h.kind, h.confidence,
           h.confidence < 0.90                              AS is_provisional,
           (SELECT count(DISTINCT entity_id) FROM hits) > 1 AS is_ambiguous
    FROM hits h
    ORDER BY h.confidence DESC;
$$ LANGUAGE sql STABLE;

COMMENT ON FUNCTION core.resolve_entity(text) IS
  'Returns every match with its confidence. is_provisional (<0.90) means the '
  'agent must state the resolution it used; is_ambiguous means it must ASK '
  '(gate rule ASK-201) rather than take the highest score.';

COMMIT;
