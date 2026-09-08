# Pre-sprint checklist

Verified live on 2026-09-08. Re-run the verification block the morning of.

## Tier 1 — you cannot run the sprint without these

| # | thing | status | action |
|---|---|---|---|
| 1 | **GitHub** `GrottoAndrew/FDE_Assessment` | ✅ connected, pushed, tracking `origin/main` | none |
| 2 | **`ANTHROPIC_API_KEY`** in `.env` | ⬜ not set | copy `.env.example` → `.env`, fill |
| 3 | **A live Postgres** for the canonical + ISO schema | ⚠️ Supabase project `Reg-D-Implementation-Postgres` is **INACTIVE** | restore it, or `createdb` locally — see below |
| 4 | **Python venv** | ✅ `.venv` built, pytest + pyyaml installed | none |

### On item 3 — decide this before the sprint, not during

The only Supabase project on the account is paused. A cold restore takes minutes
you will not have at T-10. Two options:

    # Option A — restore the Supabase project (do this the night before)
    #   Supabase dashboard -> project -> Restore. Then:
    #   DATABASE_URL=postgresql://postgres:<pw>@db.pysxoyhoxkyjnanylqfl.supabase.co:5432/postgres

    # Option B — local Postgres, zero network dependency (recommended)
    brew install postgresql@17 && brew services start postgresql@17
    createdb fde && export DATABASE_URL="postgresql://localhost:5432/fde"
    psql "$DATABASE_URL" -f src/data/schema/001_iso_reference.sql
    psql "$DATABASE_URL" -f src/data/schema/002_canonical.sql
    psql "$DATABASE_URL" -f src/data/schema/003_agent_scopes.sql

**Option B is the recommendation.** `003_agent_scopes.sql` creates roles and RLS
policies — the least-privilege story that is slide 5 of the readout. On Supabase
you are working around their managed roles; locally you own the cluster. Nothing
in this build needs to be on the internet.

## Tier 2 — verified live, useful if the problem happens to fit

| connector | status | when it earns its place |
|---|---|---|
| **Supabase MCP** | ✅ authed (1 project, paused) | if you use hosted Postgres: `apply_migration`, `execute_sql`, `get_advisors` |
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
