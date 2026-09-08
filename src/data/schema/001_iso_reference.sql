-- =============================================================================
-- 001_iso_reference.sql
-- ISO reference tables. These are the vocabulary the rest of the schema joins to.
--
-- WHY: free-text "USA"/"U.S."/"United States" and "$"/"USD"/"dollars" are the
-- single most common source of a demo that silently double-counts. Every such
-- field is an FK to a code table, so a bad value fails at INSERT rather than at
-- the readout. Codes are the join key; labels are display-only.
--
-- Apply order: this file FIRST. Everything else FKs into it.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS iso;

-- ISO 3166-1 alpha-2 — countries -------------------------------------------
CREATE TABLE IF NOT EXISTS iso.country (
    code        char(2)     PRIMARY KEY,          -- ISO 3166-1 alpha-2
    code_a3     char(3)     NOT NULL UNIQUE,      -- ISO 3166-1 alpha-3
    numeric_code char(3)    NOT NULL,             -- ISO 3166-1 numeric
    name        text        NOT NULL,
    default_tz  text        NOT NULL,             -- IANA tz, for business-hours rules
    CONSTRAINT country_code_upper CHECK (code = upper(code))
);

-- ISO 4217 — currencies -----------------------------------------------------
CREATE TABLE IF NOT EXISTS iso.currency (
    code        char(3)     PRIMARY KEY,          -- ISO 4217 alpha
    numeric_code char(3)    NOT NULL,
    name        text        NOT NULL,
    minor_unit  smallint    NOT NULL,             -- decimal places; JPY=0, USD=2
    CONSTRAINT currency_code_upper CHECK (code = upper(code))
);

-- ISO 639-1 — languages -----------------------------------------------------
CREATE TABLE IF NOT EXISTS iso.language (
    code        char(2)     PRIMARY KEY,          -- ISO 639-1
    code_iso3   char(3)     NOT NULL,             -- ISO 639-3
    name        text        NOT NULL
);

-- ISO 3166-2 — subdivisions (states/provinces) ------------------------------
CREATE TABLE IF NOT EXISTS iso.subdivision (
    code         text       PRIMARY KEY,          -- e.g. 'US-CA'
    country_code char(2)    NOT NULL REFERENCES iso.country(code),
    name         text       NOT NULL,
    category     text       NOT NULL              -- 'state','province',...
);

-- ISO 8601 is a FORMAT, not a table. Enforced by convention instead:
--   * every timestamp column is timestamptz, stored UTC
--   * every date column is `date`
--   * every duration is an interval or an ISO-8601 duration string ('P30D')
--   * NO text columns holding dates. Ever.
COMMENT ON SCHEMA iso IS
  'ISO code tables. Join on code, display name. Timestamps: ISO-8601 / timestamptz UTC everywhere.';

-- Minimum viable seed. Extend from the official lists as needed. --------------
INSERT INTO iso.country (code, code_a3, numeric_code, name, default_tz) VALUES
    ('US','USA','840','United States of America','America/New_York'),
    ('CA','CAN','124','Canada','America/Toronto'),
    ('GB','GBR','826','United Kingdom','Europe/London'),
    ('DE','DEU','276','Germany','Europe/Berlin'),
    ('FR','FRA','250','France','Europe/Paris'),
    ('JP','JPN','392','Japan','Asia/Tokyo'),
    ('AU','AUS','036','Australia','Australia/Sydney'),
    ('IN','IND','356','India','Asia/Kolkata'),
    ('BR','BRA','076','Brazil','America/Sao_Paulo'),
    ('MX','MEX','484','Mexico','America/Mexico_City')
ON CONFLICT (code) DO NOTHING;

INSERT INTO iso.currency (code, numeric_code, name, minor_unit) VALUES
    ('USD','840','US Dollar',2),
    ('CAD','124','Canadian Dollar',2),
    ('GBP','826','Pound Sterling',2),
    ('EUR','978','Euro',2),
    ('JPY','392','Yen',0),
    ('AUD','036','Australian Dollar',2),
    ('INR','356','Indian Rupee',2),
    ('BRL','986','Brazilian Real',2),
    ('MXN','484','Mexican Peso',2)
ON CONFLICT (code) DO NOTHING;

INSERT INTO iso.language (code, code_iso3, name) VALUES
    ('en','eng','English'), ('es','spa','Spanish'), ('fr','fra','French'),
    ('de','deu','German'),  ('ja','jpn','Japanese'), ('pt','por','Portuguese')
ON CONFLICT (code) DO NOTHING;

INSERT INTO iso.subdivision (code, country_code, name, category) VALUES
    ('US-CA','US','California','state'), ('US-NY','US','New York','state'),
    ('US-TX','US','Texas','state'),      ('US-IL','US','Illinois','state'),
    ('CA-ON','CA','Ontario','province'), ('CA-BC','CA','British Columbia','province')
ON CONFLICT (code) DO NOTHING;
