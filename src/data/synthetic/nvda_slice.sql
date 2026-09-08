-- =============================================================================
-- nvda_slice.sql — the NVDA demonstration slice.
-- Idempotent. Apply after 005.  make seed-nvda
--
-- Synonyms are a RESOLUTION AID, not an assertion. Anything below 0.90
-- confidence is a provisional match: the agent answers with the resolution it
-- used ("read as NVIDIA Corporation, CIK 0001045810") or it escalates. Silently
-- resolving "Nvidea" to a $4T issuer and answering about it is the failure this
-- table has to avoid creating.
-- =============================================================================

INSERT INTO core.entity (entity_id, entity_type, display_name, country_code, language_code)
VALUES ('0001045810', 'issuer', 'NVIDIA Corporation', 'US', 'en')
ON CONFLICT (entity_id) DO UPDATE SET display_name = EXCLUDED.display_name;

INSERT INTO core.entity_xref (entity_id, source_system, source_id, match_method, match_score)
VALUES ('0001045810', 'edgar',    '0001045810',   'exact', 1.000),
       ('0001045810', 'openfigi', 'BBG000BBJQV0', 'exact', 1.000)
ON CONFLICT (source_system, source_id) DO NOTHING;

INSERT INTO md.security (figi, ticker, cik, entity_id, security_name,
                         primary_mic, currency_code, country_code)
VALUES ('BBG000BBJQV0', 'NVDA', '0001045810', '0001045810',
        'NVIDIA Corporation Common Stock', 'XNGS', 'USD', 'US')
ON CONFLICT (figi) DO NOTHING;

-- --- Name synonyms -----------------------------------------------------------
INSERT INTO core.entity_synonym (entity_id, synonym, kind, confidence, source) VALUES
  -- exact, machine-verifiable
  ('0001045810', 'NVIDIA Corporation',        'legal_name',                1.000, 'edgar:conformed_name'),
  ('0001045810', 'NVIDIA Corp',               'short_name',                0.990, 'edgar:common_usage'),
  ('0001045810', 'NVIDIA',                    'short_name',                0.980, 'edgar:common_usage'),
  ('0001045810', 'Nvidia',                    'short_name',                0.980, 'common_usage'),
  ('0001045810', 'NVDA',                      'ticker',                    0.990, 'openfigi'),
  -- vendor-qualified symbols: unambiguous because the venue is named
  ('0001045810', 'NASDAQ:NVDA',               'exchange_qualified_ticker', 0.990, 'vendor'),
  ('0001045810', 'XNAS:NVDA',                 'exchange_qualified_ticker', 0.990, 'iso10383'),
  ('0001045810', 'NVDA US Equity',            'exchange_qualified_ticker', 0.980, 'bloomberg'),
  ('0001045810', 'NVDA.O',                    'exchange_qualified_ticker', 0.980, 'refinitiv_ric'),
  -- misspellings: real ones advisors type. Confidence deliberately below the
  -- 0.90 provisional threshold so a match here can never resolve silently.
  ('0001045810', 'Nvidea',                    'misspelling',               0.750, 'observed'),
  ('0001045810', 'Nvida',                     'misspelling',               0.750, 'observed'),
  ('0001045810', 'NVDIA',                     'misspelling',               0.720, 'observed'),
  ('0001045810', 'Nivida',                    'misspelling',               0.700, 'observed'),
  ('0001045810', 'NIVIDIA',                   'misspelling',               0.700, 'observed'),
  ('0001045810', 'Invidia',                   'misspelling',               0.650, 'observed'),
  ('0001045810', 'Nvidia Corportation',       'misspelling',               0.700, 'observed'),
  ('0001045810', 'Nvidia Corperation',        'misspelling',               0.700, 'observed'),
  ('0001045810', 'NVIDA Corporation',         'misspelling',               0.700, 'observed'),
  ('0001045810', 'nvidiacorp',                'misspelling',               0.680, 'observed'),
  ('0001045810', 'NVD',                       'misspelling',               0.400, 'observed'),
  -- phonetic: how it gets dictated into a note
  ('0001045810', 'en vidia',                  'phonetic',                  0.550, 'observed'),
  ('0001045810', 'in vidia',                  'phonetic',                  0.500, 'observed')
ON CONFLICT (entity_id, synonym, kind) DO NOTHING;

-- NOT ADDED, on purpose: 'TRT:NVDA' is Nvidia CDR (CAD Hedged) on Toronto — a
-- different security, a different issuer, the same four letters. It was found
-- live during source research. Adding it here would make a Canadian CDR
-- resolvable as US common, which is gap G-06 with a working example.

-- --- One quote row, labeled synthetic ----------------------------------------
-- source='synthetic_fixture', not 'yahoo_chart_v8'. This row was never fetched,
-- and a fixture wearing a real source name is how a demo number ends up in a
-- readout. The live poller writes rows with the real source and its own delay.
DELETE FROM md.quote_snapshot WHERE source IN ('synthetic_fixture','yahoo_chart_v8');
INSERT INTO md.quote_snapshot
    (figi, last, prev_close, currency_code, source, delay_seconds, as_of_at_utc, session, is_halted)
VALUES ('BBG000BBJQV0', 226.040000, 230.360000, 'USD', 'synthetic_fixture', 900,
        now() - interval '15 minutes', 'regular', false);
