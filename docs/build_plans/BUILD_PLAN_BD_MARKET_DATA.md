# Build plan: advisor quote-and-disclosure desk (independent broker-dealer)

Status: **in force**. Sponsor decisions of 2026-09-08 are applied — registry,
schema, policies, tests, and cost model are updated. `make tdd` 40/40,
`pytest tests/` 51/51. No guardrail was weakened to get there.

## The problem, in one sentence
> An advisor asks for a US equity's current quote, the disclosure or macro event
> behind a move, and what that implies for a position they already hold — and the
> firm needs every answer cited, supervised, and cheap enough to run at desk volume.

## Who asks, and what they do with the answer

| actor | task | frequency | cost of a wrong answer |
|---|---|---|---|
| Registered rep (advisor) | "Where is AAPL bid/ask right now?" | very high | quotes a stale/unentitled price to a client; Rule 603(c) display issue |
| Registered rep | "Why is it down 6%?" | medium | attributes a move to the wrong cause; unfounded claim to a client |
| Registered rep | "What's my client's position worth?" | high | T-1 share count × live price = wrong after any intraday trade |
| Supervisory principal | "Which interactions tripped a WSP rule?" | daily | a missed flag is a 3110 finding, not a bug |
| Ops / platform | "What failed overnight, and did anything fake a result?" | daily | a silent fallback is indistinguishable from a correct answer |

---

## Sponsor decisions applied (2026-09-08)

| gap | decision | where it lives now |
|---|---|---|
| G-01 | Build the call-graph test; parent→child synchronous calls stand | ADR-0006 accepted; 4 contract tests; `calls`/`parent` in the registry |
| G-02 | Delayed Yahoo quotes this sprint, under the monthly cap; entitled feed in sprint 2 | ADR-0008; `src/common/quote_budget.py` + 11 tests; `md.quote_call_budget` |
| G-07 | One money rule, Rule 612 compliant, no front/back translation | ADR-0007; `core.money` = `numeric(20,6)`; `core.is_rule612_increment` |
| G-08 | Tie into Orion; live pull on "current", Orion on "prior close" | hardcoded routing rule on the desk orchestrator; HEU-001; ASK-206/207 |
| G-11 | Reg BI / 2210 out of scope; internal viewing + chat only | `supervision_orchestrator` and `wsp_flag_agent` marked `stub`; `ops.advisor_interaction.channel` CHECK; BLK-005 blocks client-facing output |
| G-14 | Sonnet default for all source and DB pulls | ADR-0009; `model` on every registry node; `cost_model.py` reads the registry |
| G-17 | Macro news = general web search over reputable sources; relevancy/reranking out of scope | `macro_news_scan_agent`; `news.source` allowlist; `news.candidate_link.asserted` pinned false |
| — | Supabase out of scope; local Postgres only | `.mcp.json` emptied, `.env.example` rewritten |

### Where Opus still earns its price

Sonnet handles every retrieval. Opus is reserved for four decisions where being
wrong is a judgment error rather than a retrieval error, and where the cost of
the error exceeds the model delta by orders of magnitude:

1. **`discrepancy_agent`** — Orion says 1,200 shares, the feed implies 1,000.
   Deciding *which source is authoritative for this field* is arbitration.
2. **`red_team_agent`** — falsifying a claim requires constructing the case
   against it. A weaker model agrees too easily, and an agreeable red team is
   worse than none, because it manufactures confidence.
3. **`heuristic_override_agent`** — it supersedes every other agent's output.
   The one component allowed to overrule the rest is the wrong place to save.
4. **`advisor_desk_orchestrator`** — the single commit point, and the only node
   that sees every sub-agent's output at once, which is where a contradiction is
   visible at all.

Everything else is retrieval with a schema. Sonnet does that at 40% of the cost,
and `make cost VOL=5000` puts the routed configuration at ~62% below all-Opus.
Moving the orchestrator to Sonnet saves another ~9 points — an unmeasured quality
bet, so it stays unmade.

---

## 1. Hierarchy — three orchestrators, one parent

The repo's silo rule (one orchestrator per domain, out-of-domain work goes to
`ops.handoff_queue` and is dropped) is written for **asynchronous** back-office
work. An advisor Q&A turn is synchronous: the answer needs a quote *and* a filing
*and* a position in one turn. Enqueuing to a sibling and dropping would return an
empty answer. This is a real inconsistency with the scaffold and it is resolved
explicitly rather than ignored — see Gap G-01.

```
                        gate_agent  (runs first, no data access)
                              |
                   advisor_desk_orchestrator          [domain: advisor_desk]  OPUS
                   owns the single commit point
                   /              |             \
   quote_snapshot_agent   research_orchestrator   advisor_answer_agent
   (tier 0: no model)     [domain: research] SONNET   (composes, cites, never fetches)
                            /            \
              filing_fact_agent     macro_news_scan_agent
                (SONNET)                 (HAIKU)

   supervision_orchestrator  [domain: supervision]  — reads the desk's output,
   the desk cannot clear its own flag                 writes ops.flag / ops.hitl_queue
        |
   wsp_flag_agent  (HAIKU + deterministic pre-filter)

   failure_triage_agent  (system, orchestrator "*", HAIKU) — reads ops.failure_log
   red_team_agent · discrepancy_agent · heuristic_override_agent  (system, unchanged)
```

**Why supervision is a separate silo and not a sub-agent of the desk:** an
orchestrator that both answers the advisor and decides whether that answer was
compliant can suppress its own flag. Separation of duties here is structural, not
procedural — the desk role has no `INSERT` on `ops.flag`.

**Parent → child call contract (new, needs a contract test):** a parent
orchestrator may call a *declared* child synchronously; a child never calls its
parent; siblings never call each other. `ops.handoff_queue` keeps its existing
meaning — out-of-domain *observations*, dropped, drained asynchronously (e.g. the
desk notices a suitability concern; it records it for supervision and does not
reason about it).

---

## 2. Tasks → agents

One line, one verb, no "and" (`test_every_agent_has_exactly_one_task`).

| agent | single task | data scope | write scope | model tier | escalates when |
|---|---|---|---|---|---|
| `quote_snapshot_agent` | "Return one quote snapshot for one symbol." | `md.quote_snapshot`, `core.v_entity_resolved`, `sec.security_master` | `[]` | **tier 0 — no model** | symbol resolves to 0 or >1 security; quote older than `max_staleness_seconds`; bid > ask (crossed); security halted |
| `macro_news_scan_agent` | "Return published headlines matching one indexed query." | `news.headline`, `news.source` | `[]` | haiku-4.5 | zero licensed sources cover the query window; source is not on the allowlist |
| `filing_fact_agent` | "Return one disclosed fact for one CIK from one EDGAR filing." | `edgar.filing`, `edgar.xbrl_fact`, `edgar.chunk` (vector) | `[]` | sonnet-5 | fact is not XBRL-tagged and not extractable from a cited item; two filings disclose conflicting values |
| `failure_triage_agent` | "Classify one failed run into one remediation class." | `ops.failure_log`, `ops.hitl_queue` | `ops.flag` | haiku-4.5 | class is not in the enum; the same `inputs_hash` failed >3 times in one hour |
| `advisor_answer_agent` | "Compose one cited answer from rows already returned by other agents." | `[]` — receives rows, fetches nothing | `[]` | sonnet-5 | any input row lacks a citation key; the question requires a fact no agent returned |
| `wsp_flag_agent` | "Flag one advisor interaction against one WSP rule id." | `wsp.rule`, `ops.audit_log` | `ops.flag`, `ops.hitl_queue` | haiku-4.5 + regex pre-filter | rule id is absent from `wsp.rule`; interaction text is truncated or unavailable |

Kept verbatim from the scaffold: `gate_agent`, `red_team_agent`,
`discrepancy_agent`, `heuristic_override_agent`.

**`advisor_answer_agent` has `data_scope: []` on purpose.** It is the chatbot
surface, and it is structurally incapable of producing a fact that no upstream
agent cited — the same construction that makes `email_response_agent` unable to
send. This is the single most important design choice in the plan and it is the
one an interviewer should press on.

### Token economics, per the constraint

- **Tier 0 (no model at all):** quote fetch, spread computation, corporate-action
  adjustment, staleness check, WSP keyword pre-filter. The cheapest model is no
  model; an LLM that formats a bid/ask is pure loss.
- **Tier 1 (haiku-4.5):** intent parse, headline dedupe/classification, failure
  classification, WSP candidate scoring.
- **Tier 2 (sonnet-5):** filing extraction over a *pre-narrowed* section, answer
  composition.
- **Tier 3 (opus-5):** desk orchestrator commit decision, `red_team_agent`,
  `discrepancy_agent`, `heuristic_override_agent`. Nothing else.
- Filing text never enters a prompt whole. EDGAR full-text search → accession
  number → single Item section → chunk. Target < 4k input tokens per extraction.
- `autoCompactWindow: 500000` already implements the "compact at 50%, not 95%"
  requirement (`.claude/settings.json`). **But see Gap G-13** — compaction is
  lossy and the compacted transcript is not the record of the communication.

---

## 3. Data spine

### Entities

| entity | source system(s) | id field | canonical? | notes |
|---|---|---|---|---|
| Security | exchange feed, Orion, EDGAR | `figi` (OpenFIGI) | yes | ticker is **not** an identifier; it is reused across issuers over time |
| Issuer | EDGAR | `cik` | yes | one issuer → many securities |
| Security ↔ Issuer | EDGAR `company_tickers.json` | `(cik, figi)` | xref | ticker→CIK mapping is best-effort, not authoritative |
| Account | Orion, clearing firm | `orion_account_id`, `clearing_acct` | xref | two ids for one account is the `entity_xref` case |
| Household / contact | Redtail | `redtail_client_id` | xref | Redtail holds relationships, **not positions** |
| Position | Orion (T-1 reconciled), clearing firm (intraday) | `(account, figi, as_of)` | xref | the two disagree intraday — `discrepancy_agent`'s job |
| Filing | EDGAR | `accession_no` | yes | the citation key for every disclosure claim |
| WSP rule | firm's WSP document | `wsp_rule_id` | yes | must be a table, not a prompt |

### Storage tiering — flags for decision

| store | holds | flag |
|---|---|---|
| **Postgres (RDBMS)** — authoritative | canonical entity, security master, quote snapshots, position snapshots, `ops.*`, `wsp.rule` | **Anything cited in an answer must resolve to a Postgres row id.** Quote history is time-series: partition by trade date on day one or the table is unusable by month three |
| **pgvector (start here)** | EDGAR filing chunks, WSP corpus | **A vector hit is a pointer, never evidence.** Retrieval must return `accession_no` + item + offsets; the *text* is re-read from the filing before any claim. Separate embedding namespaces for filings vs WSP — mixing them lets a filing chunk answer a compliance question |
| **Graph DB (defer)** | issuer↔subsidiary↔officer, 13D/G groups, advisor↔household↔account↔position | **Do not build until a real query needs ≥3 hops.** Two hops is a recursive CTE. Named trigger to revisit: concentration analysis across households, or beneficial-ownership chains |

### Factoring hierarchy — precedence when sources conflict

Highest wins; a lower tier **never** overwrites a higher one, and a disagreement
is reported by `discrepancy_agent`, never silently resolved:

1. Entitled exchange/SIP quote (price, size, timestamp)
2. Clearing firm book of record (intraday quantity, cash)
3. Orion (T-1 reconciled quantity, cost basis, performance)
4. EDGAR (issuer-disclosed fundamentals; the accession number is the citation)
5. Licensed news (attribution only — never a price, never a quantity)
6. Model inference (never a fact; it composes cited facts or it escalates)

### Metrics — none of these exist until defined in `DATA_MODEL.md`

`gate_agent` rule `ASK-202` returns ASK for any metric absent there.

| metric | definition needed before it can be computed |
|---|---|
| `spread` | ask − bid, in **basis points of the mid**, from one venue or the NBBO? |
| `mid` | (bid+ask)/2 — undefined when the market is locked/crossed |
| `last` | last *consolidated* sale, or last on the primary listing venue? Includes odd lots? |
| `prev_close` | official closing price (auction) or 16:00:00 last sale? Split-adjusted? |
| `notional` | quantity × which price, sourced from which position tier? |
| `unrealized_pl` | requires cost basis (Orion) and price (feed) — two tiers, one number |

Six metrics, six ways for two agents to disagree in a demo. This table is the
antidote and it costs ten minutes.

---

## 4. Compliance surface — WSP flags as endpoints

The ask was "endpoints we can attach compliance flags for." The design is that
every agent output crosses exactly one such endpoint before an advisor sees it.

| endpoint | fires on | rule family | outcome |
|---|---|---|---|
| `POST /flag/recommendation` | output contains recommendation vocabulary ("should buy", "I'd add to") | Reg BI / FINRA 2111 | BLOCK, `ops.hitl_queue` |
| `POST /flag/retail_communication` | advisor asks for something forwardable to a client | FINRA 2210 | ASK — principal approval path |
| `POST /flag/performance_claim` | output contains a projected or annualized return | 2210(d)(1) | BLOCK |
| `POST /flag/unentitled_display` | quote returned without a valid entitlement token or NBBO context | Reg NMS 603(c) | BLOCK |
| `POST /flag/stale_quote` | snapshot age > threshold, or a halted security | firm WSP | flag + label, never silent |
| `POST /flag/retention` | every advisor-facing turn | SEA 17a-4 | write raw transcript, not the summary |

Two of these belong in `gating.yaml` as new BLOCK rules (`BLK-005`
unentitled_display, `BLK-006` recommendation_vocabulary). `BLK-003`
(legal/medical/financial advice) already covers most of the recommendation
surface — it needs a securities-specific `when` clause, not a new concept.

**Ceiling rule extension:** `HEU-003` currently says heuristics may never
override a gate BLOCK. It needs a sibling: **no heuristic may loosen a WSP flag.**
Tribal knowledge that quietly suppresses a supervisory flag is the exact failure
this whole architecture exists to prevent.

---

## 5. Unwritten rules to elicit (ask the firm directly)

Placeholders — each needs a named owner before it becomes a `heuristics.yaml`
row, per `authoring_rules`.

| candidate rule | overrides | who owns it |
|---|---|---|
| "Before 09:45 ET we quote the prior close, not the opening print" | `quote_snapshot_agent` | trading desk |
| "Halted names get a phone call, never a chatbot answer" | `advisor_answer_agent` | supervision |
| "Positions under 100 shares aren't worth a discrepancy escalation" | `discrepancy_agent` | ops |
| "8-K Item 2.02 earnings beats the news headline every time" | `macro_news_scan_agent` | research |

---

## 6. Explicitly not building

1. **Order entry, or anything that touches a trade.** Read-only by construction.
2. **Non-US securities, ADRs, options, fixed income.** The security master is
   designed to carry them (FIGI, ISO-4217, exchange MIC); nothing else is.
3. **Writes back into Orion or Redtail.** The system proposes; a human commits in
   the system of record.
4. **A real-time entitled feed.** The prototype runs on delayed data, labeled
   delayed, with the entitlement check stubbed but *present* (see G-02).

---

## 7. Gaps and inconsistencies — pragmatic, unranked by comfort

These are the things that break this build if they are not decided by a human.

**G-01 [RESOLVED] · Synchronous Q&A contradicts the silo rule.** The scaffold says
out-of-domain work is enqueued and dropped. A chatbot turn spanning quote +
filing + position cannot be async. *Resolution proposed:* declared parent→child
synchronous calls, with `handoff_queue` reserved for observations. *Needs:* a new
contract test forbidding cycles and sibling calls, or the silo is enforced by
comment only.

**G-02 [RESOLVED] · Real-time bid/ask is a licensing problem, not an engineering one.**
Consolidated real-time quotes require exchange agreements (CTA/UTP, or Nasdaq
Basic / Cboe One as alternatives), with display vs non-display distinctions and
per-user reporting — every advisor is a *professional* subscriber. Reg NMS Rule
603(c) further constrains displaying a quote to a customer without consolidated
context. *Pragmatic path:* source quotes from the clearing firm's existing
entitled feed rather than signing a new vendor contract. *Needs:* who holds the
entitlement today — the clearing firm, an existing vendor, or nobody?

**G-03 [OPEN] · EDGAR does not contain prices, and is not timely for moves.** 8-Ks
arrive within four business days; the price moved this morning. EDGAR as
*primary source* is correct for disclosure and wrong for causation. The honest
answer to "why is it down 6%?" is often "no filed disclosure explains this."
*Needs:* explicit acceptance that "unexplained" is a valid, frequent output.

**G-04 [OPEN] · EDGAR fair-access limits are real.** A declared User-Agent with contact
email is required and request rate is capped (~10/s). A fan-out of filing agents
will get the firm's IP blocked. *Needs:* one rate-limited fetch service, cached,
shared — not per-agent HTTP.

**G-05 [OPEN] · CUSIP is licensed intellectual property.** Redistributing CUSIPs
through a new internal system may exceed the firm's existing license. *Path:*
key on FIGI (open) and CIK internally; surface CUSIP only where Orion already
carries it under the firm's license.

**G-06 [RESOLVED] · Ticker is not an identifier.** Tickers are reused across issuers over
time and collide across venues. Any cache keyed on ticker will eventually return
a dead company's price. Key on FIGI, resolve ticker→FIGI at the edge.

**G-07 [RESOLVED] · Money-as-`bigint`-minor-units breaks on quotes.** `DATA_MODEL.md`
mandates `core.money_minor` (bigint, ISO-4217 minor units). Sub-$1 securities
quote in $0.0001 increments (Rule 612), and the 2024 tick-size amendments add a
half-cent increment for tick-constrained names — confirm the current compliance
date before relying on either. A USD minor unit of 2 cannot represent a
$0.1234 bid. *Resolution:* prices use `numeric(18,6)` + currency code;
`money_minor` stays for settled amounts. **This is a direct conflict with a
repo-wide rule and needs an ADR, not a workaround.**

**G-08 [RESOLVED] · T-1 quantity × real-time price is wrong, and looks right.** Orion
positions are reconciled to the prior close. Any intraday trade makes the
notional silently incorrect. *Resolution:* quantity carries `as_of` and its
source tier; an answer combining a T-1 quantity with a live price is labeled as
such or it escalates. *Needs:* does the firm have intraday positions from the
clearing firm, or only Orion?

**G-09 [OPEN] · Redtail holds no positions.** It is the CRM (households, contacts,
notes, workflows). "Integrate with Orion and Redtail" means two different
integrations against two different data models — even though Orion has owned
Redtail since 2022. Position questions route to Orion; relationship and
suitability context routes to Redtail.

**G-10 [OPEN] · Corporate actions silently invalidate history.** A split makes every
cached prior close wrong. Adjusted vs unadjusted must be an explicit column, not
a convention. *Needs:* a corporate-actions source (the clearing firm usually has
one).

**G-11 [SCOPED OUT] · Reg BI and 2210 belong to the compliance suite, not this
sprint.** Sponsor decision: this is internal viewing and internal chat, not a
customer-facing surface. What is built now is the *seam*, so the suite attaches
later without a migration: `ops.advisor_interaction` is the join key every flag
will hang on, its `channel` CHECK admits only `internal_chat`, `wsp.rule` ships
empty with `is_active` false, `supervision_orchestrator` holds the sole write on
`ops.flag`, and `BLK-005` blocks a request to format output for a client.
*Residual, stated plainly:* nothing here evaluates whether an answer is a
recommendation. That is deferred, not solved.

**G-12 [CONFIRMED] · "Agent for errors" is two different agents.** (a) `failure_triage_agent`
— classify a failed *run* (ops); (b) a `quote_integrity_agent` — detect bad
*data* (crossed bid/ask, stale timestamp, price outside LULD bands). This plan
builds (a) and folds (b) into `quote_snapshot_agent` as deterministic hardcoded
rules. *Needs:* confirmation that this is the intended split.

**G-13 [RESOLVED] · Compaction at 50% conflicts with books-and-records.** Compaction is
lossy by design; SEA 17a-4 retention applies to the communication, not to a
summary of it. *Resolution:* persist the raw turn to the retention store
**before** compaction. Token economics operate on the working context; the
record of the communication is not the working context.

**G-14 [RESOLVED] · Model routing has two sources of truth.** `AGENT_REGISTRY.yaml` has no
`model` field; `scripts/cost_model.py` hardcodes an `AGENTS` routing table. They
will drift, and the ROI slide will describe a system that does not exist.
*Resolution:* add `model_tier` to the registry, have `cost_model.py` read it, and
add a contract test that every agent declares one.

**G-15 [RESOLVED] · Golden cases cannot assert live prices.** A market-data eval that hits a
live feed is non-deterministic and will fail at 09:30 for reasons unrelated to
the code. *Resolution:* frozen fixtures — recorded quote payloads with fixed
timestamps — and separate, non-gating connectivity smoke checks.

**G-16 [RESOLVED] · "OSS" is ambiguous.** Read here as open/public sources (SEC, Federal
Reserve/FRED, BLS, exchange notices). If it meant licensed newswires, source
licensing and redistribution rights become a blocking prerequisite, not a
detail.

**G-17 [RESOLVED] · Macro news is a web-search agent, not a licensed feed.**
`macro_news_scan_agent` queries reputable public sources against the
`news.source` allowlist and returns *candidate* links with a stated basis —
`geography_named` catches the case where an earthquake in Colombia bears on a
miner operating there. It never states a price impact. Relevancy scoring and
reranking are explicitly out of scope; `news.candidate_link.asserted` is pinned
false by CHECK so nothing in this prototype can promote a candidate to a cause.
*Residual:* without ranking, a 24-hour window on a large-cap returns dozens of
links and the advisor does the filtering. That is honest, and it is the argument
for the reranking agent later.

**G-18 [RESOLVED] · `gate_agent` has no market-data rules yet.** `gating.yaml` is written
for a sales domain. Without `BLK-005`/`BLK-006` and a securities clause on
`BLK-003`, the gate will PROCEED on "should my client buy NVDA before earnings."

---

## 8. Implied assumptions, stated

1. Read-only against every external system; no order entry, no CRM writes.
2. US-listed equities only; the schema anticipates more, the agents do not.
3. Delayed market data in the prototype, explicitly labeled, with the entitlement
   check present but stubbed.
4. Advisors are professional subscribers for market-data licensing purposes.
5. The firm's WSPs can be reduced to a rule table with ids. If they cannot, the
   flag endpoints have no referent.
6. Postgres is the system of record for anything cited; the vector store is an
   index, never a source.
7. "Previous price" means the official prior-session close until defined otherwise.
8. Advisor identity is authenticated upstream; `core.actor_role` carries it, and
   `ASK-102` fires when it does not.
9. Every escalation is a success. A desk that returns "I can't source that" is
   working as designed.

---

## 9. Execution order (fits the 150-minute clock)

| block | work | gate to proceed |
|---|---|---|
| T-0 → T-10 | confirm G-02, G-08, G-17 with the sponsor | these three change the build |
| T-10 → T-25 | `004_domain.sql`: security master, quote snapshot, position snapshot, filing, wsp.rule; metric rows in `DATA_MODEL.md` | `make tdd` green |
| T-25 → T-40 | registry entries + golden cases (frozen fixtures, per G-15) | `make tdd` green |
| T-40 → T-55 | `BLK-005`, `BLK-006`, WSP ceiling heuristic, retry unchanged | safety cases written before agents exist |
| T-55 → T-95 | `quote_snapshot_agent` (tier 0) → `advisor_answer_agent` → `filing_fact_agent` → `wsp_flag_agent` → `macro_news_scan_agent` → `failure_triage_agent` | `make evalq` after each |
| T-95 → T-105 | reserved debug slot | do not spend early |
| T-105 → T-120 | refactor pass, full eval, baseline | safety 100% or a named gap |
| T-120 → T-150 | readout | build nothing |

Cut order if behind: `macro_news_scan_agent`, then `failure_triage_agent`, then
`filing_fact_agent`. **Never cut** the gate, the WSP flag path, the retry policy,
the audit log, or the eval run.

## Success criteria for the demo

- [ ] smoke tier 100%, safety categories 100%
- [ ] one end-to-end path: advisor question → gate → quote + filing → cited answer
- [ ] one deliberate escalation shown on purpose (ambiguous ticker, or crossed quote)
- [ ] one WSP flag fired on a recommendation-shaped question, visible in `ops.flag`
- [ ] one failure shown failing loudly, with `ops.failure_log` and no substituted default

---

## 10. The NVDA polling slice

`scripts/poll_nvda.py` — one cycle per invocation, driven by cron rather than a
long-lived process. 16 tests, run against recorded payloads.

### The two URLs in the brief are JavaScript shells

Both render client-side; fetching them returns an empty app frame. The endpoints
those pages call are what the poller uses:

| brief | actual data endpoint |
|---|---|
| `sec.gov/edgar/browse/?CIK=1045810` | `data.sec.gov/submissions/CIK0001045810.json` |
| `finance.yahoo.com/chart/NVDA#<blob>` | `query1.finance.yahoo.com/v8/finance/chart/NVDA` |

The base64 blob decodes to a UI layout — 1-minute bars, regular session only,
split/dividend adjusted, America/New_York — reproduced verbatim in `CHART_PARAMS`.

### The schedule does not fit the cap

    make pollplan IV=15 CAP=500
    polls/day 27 · trading days 21 · polls/month 567 · cap 500
    VERDICT  DOES NOT FIT — 67 calls over, before a single advisor request

09:30–16:00 at 15-minute spacing is 27 polls a day, 567 a month, for one symbol.
`--once` refuses to start on a schedule that cannot stay under the cap, rather
than discovering it on the 25th. Three ways out, in order of preference:

1. Raise `QUOTE_MONTHLY_CALL_LIMIT` to ≥ 667 (567 + headroom for ad-hoc asks).
2. Poll every 20 minutes: 420/month, 80 calls of headroom — thin.
3. Keep 15 minutes and accept that pacing refuses the last few polls each day.

At 15-minute spacing the cache never helps the poller itself (TTL 60s), but it
covers every advisor request landing between ticks, and that is where the
headroom goes.

### What this source cannot do

**No bid, no ask, no spread.** The chart endpoint returns last, previous close,
and OHLCV. The desk's headline feature — bid/ask/spread — is not servable from
it. `quote_snapshot_agent` returns INDETERMINATE for those fields rather than
deriving a spread from OHLC, which would be a fabricated number wearing a real
timestamp. Golden case `NVDA-002`. This is a capability gap against the brief,
not a formatting one, and it closes only with the entitled feed.

Also absent: halt status, and prices arrive **adjusted** (the layout sets
`adj: true`), so a cached prior close silently changes after a split — gap G-10
with a live instance.

### EDGAR costs almost nothing if asked correctly

Conditional GET with `If-None-Match`/`If-Modified-Since`. One issuer files a few
times a month, so nearly every 15-minute poll returns 304 — no body, no parsing,
no quota. `EDGAR_USER_AGENT` is mandatory and the poller refuses to run without
it; the SEC fair-access policy requires a declared identity, and running without
one risks the firm's IP rather than the script.

### Not run here

This container's egress policy returns 403 CONNECT for `data.sec.gov`,
`www.sec.gov`, `query1.finance.yahoo.com`, and `finance.yahoo.com`, on both the
direct and the WebFetch path. No live pull happened. The poller is proven
offline against recorded payloads and needs one run on a machine with egress
before any number from it is quoted.

### Two bugs the tests caught

1. **Pacing starvation.** Recomputing the daily cap from the live balance after
   each spend shrinks it as the day is spent: 500 over 27 days gives 18, but
   after 17 calls the same formula gives 17 and refuses the 18th. Fixed to
   compute from the start-of-day balance.
2. **A cache that cron erases.** The budget's cache lived in process memory. A
   cron-invoked poller is a new process every tick, so the TTL never fired and
   every tick spent a call it did not have to. The cache is now serialized into
   `eval_output/.poll_state.json` with the counters.
