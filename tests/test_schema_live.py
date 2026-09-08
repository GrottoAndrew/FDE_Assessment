"""Structural assertions against a live local Postgres. Skipped when none runs.

These are the checks that reading the DDL cannot make: the ops.flag dependency
that broke the first migration run was found here, not in a file.
"""
import shutil
import subprocess

import pytest

DSN = "postgresql:///fde"


def _run(sql: str, quiet: bool = True):
    """SQL goes in on stdin. Interpolating it into a shell -c string is a quoting
    bug waiting to happen, and it was one."""
    flags = "-At" if quiet else ""
    return subprocess.run(["su", "postgres", "-c",
                           f"psql -h /tmp -p 5432 -U postgres -d fde {flags} -f -"],
                          input=sql, capture_output=True, text=True, timeout=20)


def _psql(sql: str) -> str:
    return _run(sql).stdout.strip()


def _available() -> bool:
    if not shutil.which("psql"):
        return False
    r = subprocess.run(["su", "postgres", "-c", "psql -h /tmp -p 5432 -U postgres -d fde -At -f -"],
                       input="select 1;", capture_output=True, text=True, timeout=20)
    return r.returncode == 0 and r.stdout.strip() == "1"


pytestmark = pytest.mark.skipif(not _available(), reason="no local fde database running")


def test_no_uuid_entity_keys_survive():
    out = _psql("SELECT count(*) FROM information_schema.columns "
                "WHERE data_type='uuid' AND column_name IN ('entity_id','merged_into')")
    assert out == "0", "a uuid canonical key means the same company can be two entities"


def test_every_issuer_id_is_a_ten_digit_cik():
    out = _psql("SELECT count(*) FROM core.entity WHERE entity_type='issuer' AND entity_id !~ '^[0-9]{10}$'")
    assert out == "0"


def test_the_shape_constraint_rejects_a_uuid_issuer():
    r = _run("INSERT INTO core.entity (entity_id, entity_type, display_name) "
             "VALUES ('a3f1c2e4-0000-4000-8000-000000000001', 'issuer', 'Bogus');", quiet=False)
    assert "entity_id_shape" in (r.stdout + r.stderr), \
        "the canonical id shape must be a database constraint, not a convention"


def test_every_foreign_key_has_a_supporting_index():
    out = _psql("""SELECT count(*) FROM pg_constraint c
        WHERE c.contype='f'
          AND c.connamespace::regnamespace::text IN ('core','md','pos','edgar','news','wsp','ops')
          AND NOT EXISTS (SELECT 1 FROM pg_index i WHERE i.indrelid=c.conrelid AND i.indkey[0]=c.conkey[1])""")
    assert out == "0", "an unindexed FK is a sequential scan on every join once the table is real"


def test_money_columns_all_use_the_core_domain():
    out = _psql("""SELECT count(*) FROM information_schema.columns
        WHERE table_schema IN ('core','md','pos')
          AND column_name ~ '(price|bid|ask|close|basis|cost)'
          AND column_name !~ '(_at|_source|_size)'
          AND COALESCE(domain_schema||'.'||domain_name,'') <> 'core.money'""")
    assert out == "0", "a money column outside core.money is the second money rule ADR-0007 removed"


def test_the_resolver_flags_a_misspelling_as_provisional():
    out = _psql("SELECT is_provisional FROM core.resolve_entity('Nvidea') LIMIT 1")
    assert out == "t", "a sub-0.90 match must never resolve silently"


def test_the_resolver_matches_the_canonical_name_exactly():
    out = _psql("SELECT entity_id FROM core.resolve_entity('NVIDIA Corporation') LIMIT 1")
    assert out == "0001045810"


def test_an_unknown_name_resolves_to_nothing_rather_than_a_guess():
    assert _psql("SELECT count(*) FROM core.resolve_entity('Acme Widgets Holdings')") == "0"


def test_no_synonym_resolves_to_two_entities():
    assert _psql("SELECT count(*) FROM core.v_synonym_collision") == "0"


def test_no_agent_role_writes_outside_ops():
    out = _psql("""SELECT count(*) FROM information_schema.role_table_grants
        WHERE grantee LIKE 'agent_%' AND privilege_type IN ('INSERT','UPDATE','DELETE')
          AND table_schema <> 'ops'""")
    assert out == "0", "sub-agents write only ops.* sinks; the orchestrator commits"
