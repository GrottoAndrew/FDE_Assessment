"""
Contract tests — the structural invariants of the system.

These run in milliseconds and need no database, no model, and no network. They
are the red-green loop during the sprint: they fail the moment someone widens an
agent's data scope, adds an unowned heuristic, or ships a rule with no golden
case behind it. Run with `make tdd`.

They test the DESIGN, not the behavior. Behavior is the golden set's job.
"""
import re

import pytest

SYSTEM_AGENTS = {"gate_agent", "red_team_agent", "discrepancy_agent",
                 "heuristic_override_agent"}


# --- agent narrowness --------------------------------------------------------
def test_every_agent_has_exactly_one_task(registry):
    for a in registry["agents"]:
        task = a["single_task"]
        # count sentence-ending periods only; dots inside paths like foo.yaml don't count
        sentences = len(re.findall(r"\.(?:\s|$)", task))
        assert sentences <= 1, f"{a['name']}: {sentences} sentences => multiple jobs"
        assert not re.search(r"\b(and|also)\b", task.lower()), \
            f"{a['name']}: '{task}' joins two jobs with 'and'. Split it."


def test_no_vague_agent_names(registry):
    banned = {"assistant", "helper", "manager", "handler", "general", "smart", "ai"}
    for a in registry["agents"]:
        tokens = set(a["name"].lower().split("_"))
        assert not (tokens & banned), \
            f"{a['name']} uses a vague noun {tokens & banned}. Name the task, not the role."


def test_every_agent_declares_a_data_scope(registry):
    for a in registry["agents"]:
        assert "data_scope" in a, f"{a['name']} has no data_scope: it would inherit ambient access"


def test_gate_agent_has_no_data_access(registry):
    gate = next(a for a in registry["agents"] if a["name"] == "gate_agent")
    assert gate["data_scope"] == [], \
        "gate_agent must decide without reading. Data access here is a scope leak."


def test_write_scopes_are_minimal(registry):
    """Only ops.* sinks may be written by sub-agents. Domain writes go through
    the orchestrator so there is one commit point to audit."""
    for a in registry["agents"]:
        for tbl in a.get("write_scope", []):
            assert tbl.startswith("ops."), \
                f"{a['name']} writes {tbl}; sub-agents write only ops.* sinks"


def test_email_agent_cannot_send(registry):
    a = next(x for x in registry["agents"] if x["name"] == "email_response_agent")
    assert a.get("write_scope") == [], "a drafting agent with write access can send"


def test_system_agents_present(registry):
    names = {a["name"] for a in registry["agents"]}
    missing = SYSTEM_AGENTS - names
    assert not missing, f"system agents deleted: {missing}. These survive any domain swap."


# --- silo integrity ----------------------------------------------------------
def test_each_agent_reports_to_exactly_one_orchestrator(registry):
    domains = {o["domain"] for o in registry["orchestrators"]}
    for a in registry["agents"]:
        orch = a["orchestrator"]
        if orch == "*":
            assert a.get("kind") == "system", f"{a['name']} is cross-domain but not a system agent"
            continue
        names = {o["name"] for o in registry["orchestrators"]}
        assert orch in names, f"{a['name']} reports to unknown orchestrator {orch}"
    assert len(domains) == len(registry["orchestrators"]), "two orchestrators share a domain"


def test_orchestrators_declare_cross_domain_policy(registry):
    for o in registry["orchestrators"]:
        if o.get("status") == "stub":
            continue
        assert o.get("cross_domain_policy"), \
            f"{o['name']} has no cross_domain_policy: the silo is unenforced"


# --- gating ------------------------------------------------------------------
def test_gates_have_ids_and_reasons(gating):
    for bucket in ("block", "ask_sensitive", "ask_indeterminate"):
        for rule in gating[bucket]:
            assert re.match(r"^(BLK|ASK)-\d{3}$", rule["id"]), f"bad gate id {rule['id']}"
            assert rule.get("reason") or rule.get("question"), \
                f"{rule['id']} has neither a reason nor a question"


def test_ask_rules_ask_exactly_one_question(gating):
    for bucket in ("ask_sensitive", "ask_indeterminate"):
        for rule in gating[bucket]:
            q = rule["question"]
            assert q.count("?") == 1, f"{rule['id']} asks {q.count('?')} questions; ask one"


def test_gate_ids_unique(gating):
    ids = [r["id"] for b in ("block", "ask_sensitive", "ask_indeterminate") for r in gating[b]]
    assert len(ids) == len(set(ids)), "duplicate gate ids"


# --- heuristics --------------------------------------------------------------
def test_every_heuristic_has_an_owner_and_rationale(heuristics):
    for r in heuristics["rules"]:
        assert r.get("owner"), f"{r['id']} has no owner — it is a guess, not a rule"
        assert len(r.get("rationale", "").strip()) > 40, \
            f"{r['id']} rationale too thin to defend in the readout"


def test_heuristics_cannot_override_a_gate_block(heuristics):
    ceiling = [r for r in heuristics["rules"] if r["id"] == "HEU-003"]
    assert ceiling, "the ceiling rule is missing: heuristics could override a safety gate"
    assert ceiling[0]["then"].get("halt") is True


def test_heuristic_conflicts_escalate_rather_than_resolve(heuristics):
    cp = heuristics["conflict_policy"]
    assert "hitl" in cp["on_multiple_matches_opposite_outcome"].lower()
    assert "hitl" in cp["on_precondition_null"].lower()


def test_every_heuristic_is_audited(heuristics):
    for r in heuristics["rules"]:
        assert r.get("audit") == "required", f"{r['id']} fires without an audit row"


# --- retry -------------------------------------------------------------------
def test_retry_is_bounded(retry):
    assert 1 <= retry["defaults"]["max_attempts"] <= 3


def test_decisions_are_never_retried(retry):
    for kind in ("gate_block", "permission_denied", "indeterminate_result"):
        assert kind in retry["never_retry"], f"{kind} must not be retryable"


def test_exhaustion_fails_loud(retry):
    ex = retry["on_exhaustion"]
    assert ex["action"] == "FAIL_LOUD"
    assert ex["notification"]["channels"], "exhaustion with no notification is a silent failure"
    joined = " ".join(ex["steps"]).lower()
    assert "partial" in joined and "hitl" in joined


# --- golden set --------------------------------------------------------------
def test_golden_cases_are_wellformed(golden):
    ids = [c["id"] for c in golden]
    assert len(ids) == len(set(ids)), "duplicate golden case ids"
    for c in golden:
        assert c["assert"] in {"exact", "contains"}, f"{c['id']}: unknown assertion mode"
        assert len(c.get("why", "")) > 20, f"{c['id']} has no stated purpose; it will rot"


def test_golden_set_covers_every_safety_category(golden):
    required = {"gate_block", "gate_persistence", "ceiling_rule",
                "least_privilege", "fail_loud", "no_send_capability"}
    covered = {c.get("category") for c in golden}
    assert not (required - covered), f"safety categories with no golden case: {required - covered}"


def test_every_heuristic_has_a_positive_and_negative_case(heuristics, golden):
    """A rule with only a firing test will over-fire in production and pass evals."""
    cats = {c.get("category") for c in golden}
    assert "override_fires" in cats, "no test that a heuristic fires"
    assert "override_declines" in cats, "no test that a heuristic declines to fire"


def test_smoke_tier_is_small_enough_to_run_constantly(golden):
    smoke = [c for c in golden if c["tier"] == "smoke"]
    assert 1 <= len(smoke) <= 6, "smoke tier must stay tiny or it stops being run"


# --- schema ------------------------------------------------------------------
def test_no_text_date_columns(root):
    """ISO-8601 discipline: dates live in date/timestamptz, never in text."""
    for sql in (root / "src/data/schema").glob("*.sql"):
        for i, line in enumerate(sql.read_text().splitlines(), 1):
            if re.search(r"\b\w*(date|_at|timestamp)\w*\s+text\b", line, re.I):
                pytest.fail(f"{sql.name}:{i} stores a date as text: {line.strip()}")


def test_canonical_view_excludes_merged_entities(root):
    sql = (root / "src/data/schema/002_canonical.sql").read_text()
    assert "WHERE e.is_canonical" in sql, \
        "the canonical view must exclude merged duplicates or agents can cite stale rows"


def test_iso_tables_exist(root):
    sql = (root / "src/data/schema/001_iso_reference.sql").read_text()
    for t in ("iso.country", "iso.currency", "iso.language", "iso.subdivision"):
        assert f"CREATE TABLE IF NOT EXISTS {t}" in sql, f"missing ISO table {t}"
