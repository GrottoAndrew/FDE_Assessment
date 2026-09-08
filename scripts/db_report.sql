-- =============================================================================
-- db_report.sql — structural analysis of the live instance.  make dbreport
-- Every section should return either nothing or something you can defend.
-- =============================================================================
\echo '== 1. Canonical id uniformity: any surviving uuid entity key is a defect =='
SELECT table_schema||'.'||table_name||'.'||column_name AS uuid_entity_column
FROM information_schema.columns
WHERE data_type = 'uuid' AND column_name IN ('entity_id','merged_into');

\echo '== 2. entity_id shape by type (issuers must be 10-digit CIKs) =='
SELECT entity_type, count(*) AS rows,
       count(*) FILTER (WHERE entity_type='issuer' AND entity_id !~ '^[0-9]{10}$') AS bad_issuer_ids
FROM core.entity GROUP BY entity_type ORDER BY entity_type;

\echo '== 3. Tables with no primary key =='
SELECT n.nspname||'.'||c.relname AS table_without_pk
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE c.relkind='r' AND n.nspname IN ('core','md','pos','edgar','news','wsp','ops')
  AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conrelid=c.oid AND k.contype='p')
ORDER BY 1;

\echo '== 4. Foreign keys with no supporting index (a silent seq-scan on every join) =='
SELECT c.conrelid::regclass||' ('||a.attname||')' AS unindexed_fk
FROM pg_constraint c
JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=c.conkey[1]
WHERE c.contype='f'
  AND c.connamespace::regnamespace::text IN ('core','md','pos','edgar','news','wsp','ops')
  AND NOT EXISTS (
    SELECT 1 FROM pg_index i
    WHERE i.indrelid=c.conrelid AND i.indkey[0]=c.conkey[1])
ORDER BY 1;

\echo '== 5. Money columns: every one must be core.money, never float or bigint =='
-- domain_schema is printed on purpose: Postgres has a BUILT-IN `money` type
-- that is locale-dependent and unusable for this. 'core.money' is ours.
SELECT table_schema||'.'||table_name||'.'||column_name||' :: '||
       COALESCE(domain_schema||'.'||domain_name, data_type) AS money_like_column
FROM information_schema.columns
WHERE table_schema IN ('core','md','pos')
  AND (column_name ~ '(price|bid|ask|close|basis|amount|cost)')
ORDER BY 1;

\echo '== 6. Date/time columns that are not timestamptz or date =='
SELECT table_schema||'.'||table_name||'.'||column_name||' :: '||data_type AS bad_time_column
FROM information_schema.columns
WHERE table_schema IN ('core','md','pos','edgar','news','wsp','ops')
  AND column_name ~ '(_at|date|timestamp)'
  AND data_type NOT IN ('timestamp with time zone','date');

\echo '== 7. Synonym collisions: one string resolving to two entities =='
SELECT * FROM core.v_synonym_collision;

\echo '== 8. Synonym coverage by confidence band =='
SELECT CASE WHEN confidence >= 0.90 THEN 'authoritative (>=0.90)'
            ELSE 'provisional (<0.90, must be disclosed)' END AS band,
       count(*), array_agg(kind ORDER BY kind) FILTER (WHERE true) AS kinds
FROM (SELECT DISTINCT kind, confidence FROM core.entity_synonym) d GROUP BY 1;

\echo '== 9. The split-out desk surface =='
SELECT symbol, name, cik, price, prev_close, bid, ask, currency_code,
       price_source, delay_seconds FROM md.v_security_price;

\echo '== 10. Agent roles holding a write grant outside ops.* (must be empty) =='
SELECT grantee, table_schema||'.'||table_name AS tbl, privilege_type
FROM information_schema.role_table_grants
WHERE grantee LIKE 'agent_%' AND privilege_type IN ('INSERT','UPDATE','DELETE')
  AND table_schema <> 'ops'
ORDER BY 1;
