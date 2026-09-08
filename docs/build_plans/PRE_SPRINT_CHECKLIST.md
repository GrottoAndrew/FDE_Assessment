# Pre-sprint checklist

Verified live on 2026-09-08. Re-run the verification block the morning of.

## Tier 1 — you cannot run the sprint without these

| # | thing | status | action |
|---|---|---|---|
| 1 | **GitHub** `GrottoAndrew/FDE_Assessment` | ✅ connected, pushed, tracking `origin/main` | none |
| 2 | **`ANTHROPIC_API_KEY`** in `.env` | ⬜ not set | copy `.env.example` → `.env`, fill |
| 3 | **A live Postgres** for the canonical + ISO schema | ✅ dedicated Supabase project `krnkvkunhwwfdqeqnikg` wired via project-scoped MCP | authenticate it once — see below |
| 4 | **Python venv** | ✅ `.venv` built, pytest + pyyaml installed | none |

### On item 3 — the dedicated Supabase project

A project-scoped MCP server is committed to the repo at `.mcp.json`, pinned to
`project_ref=krnkvkunhwwfdqeqnikg` with the docs, account, database, debugging,
development, functions, and branching features enabled. Because it is project
scope rather than user scope, it travels with the GitHub clone.

Supabase agent skills are installed at `.agents/skills/` (symlinked into
`.claude/skills/`, relative links so they survive a clone) and pinned by hash in
`skills-lock.json`.

**Remaining manual step — do this before sprint day:**

    /mcp        # in Claude Code -> select `supabase` -> Authenticate (OAuth, browser)

Project-scoped MCP servers load at session start and prompt for trust the first
time, so **restart Claude Code** after authenticating. Verify with:

    /mcp        # supabase should read "connected"

Then apply the schema. Either through the MCP (`apply_migration`) or directly:

    psql "$DATABASE_URL" -f src/data/schema/001_iso_reference.sql
    psql "$DATABASE_URL" -f src/data/schema/002_canonical.sql
    psql "$DATABASE_URL" -f src/data/schema/003_agent_scopes.sql

#### Two Supabase-specific traps that affect this schema

1. **Our schemas are not `public`.** `core`, `ops`, `iso`, and the domain schema
   are custom, so they are **not** exposed through the Data API by default and
   `anon`/`authenticated` cannot reach them without an explicit `GRANT`. That is
   the behavior we want — agents connect as their own Postgres roles from
   `003_agent_scopes.sql`, not through PostgREST. Do not "fix" this by exposing
   them.
2. **RLS is row-level, not table-level.** `003_agent_scopes.sql` enables RLS on
   `core.entity`, `core.entity_xref`, and `ops.hitl_queue` as defense in depth on
   top of the GRANTs. Keep both: the GRANT decides *which tables*, the policy
   decides *which rows*. The Supabase skill's warning about `user_metadata` in
   authorization does not apply here — our policies key on
   `current_setting('app.agent_name')`, set by the runtime per invocation, not on
   a JWT claim.

**Fallback if the project is unreachable on the day:** local Postgres, zero
network dependency. Have this ready as plan B.

    brew install postgresql@17 && brew services start postgresql@17
    createdb fde && export DATABASE_URL="postgresql://localhost:5432/fde"

## Tier 2 — verified live, useful if the problem happens to fit

| connector | status | when it earns its place |
|---|---|---|
| **Supabase MCP** (account-scoped) | ✅ authed, but sees a *different* account — only `Reg-D-Implementation-Postgres` (paused) | ignore it; the project-scoped server in `.mcp.json` is the one for this build |
| **Gamma** | ✅ authed | paste `PRESENTATION_PROMPT.txt` → deck in ~1 min. Cannot *edit* an existing gamma — generate once, polish in their editor |
| **Airtable** | ✅ authed (1 empty base) | only if the interviewer hands you an Airtable base as the data source |
| **Miro** | ✅ authed | `diagram_create_mermaid` for the slide-2 architecture diagram |
| **Google Drive** | ✅ authed | if the problem set arrives as a Doc/Sheet |
| **Exa** | ✅ available | domain research at T-0 if the problem is in an unfamiliar vertical |
| **Mermaid Chart** | ⚠️ diagram tools work; its **GitHub bridge is unauthed** | irrelevant — you push with `gh`, not through Mermaid |

## Tier 3 — do NOT set up

Notion, HubSpot, Figma, Intercom, Tavily, Monte Carlo, Plaid, CourtListener all
show as unauthenticated. Leave them that way. Each is an OAuth dance you would be
doing at minute 12 of a 150-minute sprint, and none is on the critical path.

**The general rule:** every connector is a live dependency that can fail in front
of the interviewer. The build needs Postgres, a model key, and git. Everything
else is a convenience you should be able to drop mid-sprint without losing work.

## The morning-of verification block

Run this. All four must be green before you start.

    cd ~/projects/FDE_Assessment
    make tdd          # 26 contract tests, ~0.1s
    make eval         # 26 golden cases, stub adapter
    make deck         # regenerates the presentation prompt
    psql "$DATABASE_URL" -c "select count(*) from iso.currency;"   # expect 9

Plus:

    gh auth status                      # expect: Logged in to github.com as GrottoAndrew
    git -C . status --short             # expect: clean
    echo $ANTHROPIC_API_KEY | head -c 7 # expect: sk-ant-

## Gotcha found during setup

`gh auth status` prints a **stale keyring warning** — "The token in keyring is
invalid" — while `gh api user` succeeds and pushes work fine. Do not spend sprint
time chasing it. Trust `gh api user`, not `gh auth status`.
