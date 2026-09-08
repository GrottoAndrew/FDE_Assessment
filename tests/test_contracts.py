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


def test_answer_agent_cannot_fetch_or_send(registry):
    """The chatbot surface is bounded by construction, not by instruction.

    Empty data_scope means it cannot produce a fact no upstream agent cited.
    Empty write_scope means it cannot commit, send, or clear anything. Both are
    structural guarantees; a prompt saying "only use the provided rows" is not.
    """
    a = next(x for x in registry["agents"] if x["name"] == "advisor_answer_agent")
    assert a["data_scope"] == [], "an answer agent that can fetch can invent an uncited fact"
    assert a["write_scope"] == [], "an answer agent with write access can commit or send"


def test_every_agent_declares_a_model(registry):
    """G-14: model routing lived in cost_model.py while the registry knew nothing
    about it. Two sources of truth drift, and the ROI slide then describes a
    system that does not exist."""
    allowed = set(registry["meta"]["model_tiers"])
    for a in registry["agents"]:
        assert a.get("model") in allowed, \
            f"{a['name']} declares model {a.get('model')!r}, not in {sorted(allowed)}"
    for o in registry["orchestrators"]:
        assert o.get("model") in allowed, f"{o['name']} declares no valid model"


def test_opus_is_reserved_for_arbitration_and_falsification(registry):
    """Sponsor rule: sonnet for every source pull; opus only where a wrong call
    is a judgment error rather than a retrieval error."""
    allowed_opus = {"red_team_agent", "discrepancy_agent", "heuristic_override_agent"}
    for a in registry["agents"]:
        if a.get("model") == "claude-opus-5":
            assert a["name"] in allowed_opus, \
                f"{a['name']} runs on opus but is not an arbitration or falsification agent"


def test_every_agent_has_a_cost_profile(registry):
    """No profile means the unit-cost number is an estimate wearing a table."""
    for a in registry["agents"]:
        cp = a.get("cost_profile")
        assert cp and {"tokens_in", "tokens_out", "share"} <= set(cp), \
            f"{a['name']} has no cost_profile; its cost cannot be measured"
        if a["model"] == "none":
            assert cp["tokens_in"] == 0 and cp["tokens_out"] == 0, \
                f"{a['name']} claims a deterministic path but bills tokens"


def test_only_supervision_writes_the_compliance_flag(registry):
    """Separation of duties: the desk cannot raise or clear a flag on its own
    output. ops.flag has exactly one writing silo."""
    supervision = {o["name"] for o in registry["orchestrators"] if o["domain"] == "supervision"}
    for a in registry["agents"]:
        if "ops.flag" in a.get("write_scope", []):
            assert a["orchestrator"] in supervision, \
                f"{a['name']} writes ops.flag from outside the supervision silo"


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


def test_orchestrator_call_graph_is_a_tree(registry):
    """ADR-0006. A parent may call a declared child synchronously; children never
    call parents and siblings never call each other. Without this the silo is
    enforced by a comment."""
    orchs = {o["name"]: o for o in registry["orchestrators"]}
    agents = {a["name"]: a for a in registry["agents"]}

    parents: dict[str, str] = {}
    for name, o in orchs.items():
        for callee in o.get("calls", []):
            assert callee in orchs or callee in agents, f"{name} calls unknown {callee}"
            if callee in orchs:
                assert callee not in parents, \
                    f"{callee} is called by both {parents[callee]} and {name}; that is a DAG, not a silo"
                parents[callee] = name
                assert orchs[callee].get("parent") == name, \
                    f"{callee} is called by {name} but declares parent {orchs[callee].get('parent')!r}"

    # declared parent and actual caller agree in the other direction too
    for name, o in orchs.items():
        declared = o.get("parent")
        assert declared == parents.get(name), \
            f"{name} declares parent {declared!r} but is called by {parents.get(name)!r}"

    # no cycles: walk to the root from every node
    for name in orchs:
        seen, cur = set(), name
        while cur is not None:
            assert cur not in seen, f"cycle in the orchestrator graph at {cur}"
            seen.add(cur)
            cur = orchs[cur].get("parent")


def test_no_orchestrator_reaches_into_another_silo(registry):
    """A domain agent is callable only by the orchestrator it reports to.
    System agents (orchestrator '*') are callable by any of them."""
    orchs = {o["name"]: o for o in registry["orchestrators"]}
    agents = {a["name"]: a for a in registry["agents"]}
    for name, o in orchs.items():
        for callee in o.get("calls", []):
            if callee in agents:
                owner = agents[callee]["orchestrator"]
                assert owner in (name, "*"), \
                    f"{name} calls {callee}, which reports to {owner}. Cross-silo reach-in."


def test_every_domain_agent_is_reachable(registry):
    """An agent in the registry that no orchestrator calls is dead scaffolding,
    and dead scaffolding is what an interviewer finds."""
    called = {c for o in registry["orchestrators"] for c in o.get("calls", [])}
    for a in registry["agents"]:
        if a.get("kind") == "domain":
            assert a["name"] in called, f"{a['name']} is unreachable: no orchestrator calls it"


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


# --- money and provenance ----------------------------------------------------
def test_exactly_one_money_representation(root):
    """ADR-0007. One type across the store, the API, and the UI so nothing has to
    translate on the way through. Two money types is a defect class."""
    canonical = (root / "src/data/schema/002_canonical.sql").read_text()
    assert "CREATE DOMAIN core.money AS numeric" in canonical, "core.money is missing"
    assert "money_minor" not in canonical, "the minor-unit type survived; that is a second money rule"
    for sql in (root / "src/data/schema").glob("*.sql"):
        body = sql.read_text()
        assert "money_minor" not in body, f"{sql.name} still references money_minor"


def test_quote_increments_are_rule612_checked(root):
    sql = (root / "src/data/schema/004_domain.sql").read_text()
    assert "core.is_rule612_increment(bid)" in sql and "core.is_rule612_increment(ask)" in sql, \
        "quotations must be constrained to Rule 612 increments"
    assert "is_rule612_increment(last)" not in sql, \
        "executions may print sub-penny through price improvement; constraining last is wrong"


def test_every_external_price_carries_its_provenance(root):
    """A price without source, venue timestamp, and delay is not a value."""
    sql = (root / "src/data/schema/004_domain.sql").read_text()
    for col in ("source", "delay_seconds", "as_of_at_utc", "retrieved_at_utc"):
        assert col in sql, f"md.quote_snapshot must carry {col}"


def test_news_links_cannot_be_promoted_to_asserted_causes(root):
    """Relevancy ranking is out of scope, so nothing may claim causation."""
    sql = (root / "src/data/schema/004_domain.sql").read_text()
    assert "asserted" in sql and "CHECK (asserted = false)" in sql, \
        "news.candidate_link.asserted must be pinned false while ranking is out of scope"


def test_the_advisor_surface_is_internal_only(root):
    sql = (root / "src/data/schema/004_domain.sql").read_text()
    assert "CHECK (channel IN ('internal_chat'))" in sql, \
        "an internal-only surface must be enforced by a CHECK, not by scope prose"


def test_golden_cases_reference_agents_that_exist(registry, golden):
    """A case pointed at a deleted agent passes forever without testing anything."""
    known = {a["name"] for a in registry["agents"]} | {o["name"] for o in registry["orchestrators"]}
    for c in golden:
        assert c["agent"] in known, f"{c['id']} targets unknown agent {c['agent']}"


def test_golden_set_covers_every_orchestrator(registry, golden):
    targeted = {c["agent"] for c in golden}
    for o in registry["orchestrators"]:
        if o.get("status") == "stub":
            continue
        assert o["name"] in targeted, f"{o['name']} has no golden case; its routing is untested"
