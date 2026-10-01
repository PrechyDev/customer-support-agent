# Handover: end of 01-10-2026

For the next Claude Code session. Read this, then `docs/BUILD_PLAN.md` ("▶ Next session"), then `docs/SPECS.md`.

## Where we are

- **Working end to end:** Vapi web call → ngrok → FastAPI `/chat/completions` → Claude Agent SDK (Haiku 4.5) → MCP server `relaypay` → `search_knowledge_base` (in-memory BM25 over the KB).
- **Built and committed:** KB search, MCP server (Streamable HTTP on 127.0.0.1:8001, bearer token), agent sessions (locked-down SDK options, one session per call), Vapi endpoint, `/vapi/events` webhook (prewarm on call start, close on call end), conversation flow (SPECS §2b), grounding prompt.
- **Built and tested, NOT yet voice-tested:** `<say>` tags (only text inside is spoken), a limit on waiting for a call's engine (15 s), prompt rules "never claim an action you can't do" and "never say where to find something unless the KB says so".
- **Supabase (Phase 2) done:** `poetry run relaypay-db` creates the 10 tables (`migrations/001_schema.sql`, RLS on, no policies) and upserts the seed data from `data/seed/`. Safe to re-run.
- **Phase 3 built, tested offline, NOT voice-tested yet (uncommitted until the user says commit):**
  - all 7 MCP tools on Supabase: `mcp_server/tools/{accounts,cases,common}.py`, pure rules in `domain/` (spoken references, statuses, callback windows), all SQL in `db/repository.py` (`migrations/002_phase3.sql` is applied)
  - call records: `api/records.py` (conversation row, one row per turn, Vapi's end-of-call summary, `abandoned` on idle close), all in the background
  - pre-call form: `api/caller.py` reads Vapi metadata → prompt ("typed, NOT verified") + conversation row + escalation contact
  - grounding: `<say type sources>` parsed in `agent/session.py`, judged in `agent/grounding.py` → `answer_type` + `confidence_note`; "NOT GROUNDED" also logged as a warning
  - prompt: Phase 3 rules added (lookups, verification, tickets/escalations, callbacks, events, grounding A + case-3)
  - checks: 102 tests + 3 real-database tests (`RUN_DB_TESTS=1`, test schema only); a real-Supabase smoke test of every tool over MCP HTTP (no model, no Vapi; rows deleted). Tool times on the session pooler: lookups ~0.15 s, verification ~0.55 s, ticket ~0.45 s, escalation ~0.8 s.
- **Not built yet:** log-only phrase check and rate limiting (Phase 5), voice page with the form (Phase 6), deploy (Phase 7), console (Phase 8), evaluations (Phase 9), submission docs (Phase 10).

## Update 01-10-2026 (evening): console backend, production fixes, evaluations

- **Console backend built and tested** (`console/`, `db/console_store.py`, `api/console.py`, migration 006 applied to
  test and public). Contract for the frontend session: `docs/CONSOLE_API.md`. Rules: SPECS §14.
  Create the owner account: `poetry run relaypay-admin --email you@example.com` (prints a 72 h setup link; `--reset`
  for a new one). Needs `CONSOLE_SESSION_SECRET` (32+ characters) in `.env`.
- **Production fixes:** `/health/ready` (database check), voice lookups rate-limited, background record writes
  retried once (ERROR if lost), `LOG_FORMAT=json` for Cloud Run.
- **Evaluations:** `poetry run relaypay-eval` (SPECS §12). Start a backend on the test schema first, e.g. in
  PowerShell: `$env:DATABASE_SCHEMA="test"; $env:PORT="8100"; $env:MCP_PORT="8101"; poetry run relaypay-backend`,
  then `$env:DATABASE_SCHEMA="test"; poetry run relaypay-eval --base-url http://127.0.0.1:8100`. 13/13 passed.
  Score a voice call: `poetry run relaypay-eval --call <id> --scenario s4_transaction --schema public`.

## Test data vs real records

- `public` schema = the real records (tickets start at T-1001). `test` schema = a throwaway copy with its own counters, created with `DATABASE_SCHEMA=test poetry run relaypay-db`.
- Claude's smoke tests always use `test` and delete their rows. To make a whole practice call throwaway, set `DATABASE_SCHEMA=test` in `.env` and restart the backend (the startup log shows the schema).

## Running the tests

- Everything offline (no database, no Claude, no Vapi): `poetry run pytest -q`
- Plus the real-database tests (Supabase `test` schema only; they clean up): `RUN_DB_TESTS=1 poetry run pytest -q` (PowerShell: `$env:RUN_DB_TESTS="1"; poetry run pytest -q`)
- One area: `poetry run pytest -q tests/mcp_server` (or `tests/agent`, `tests/api`, `tests/domain`, `tests/kb`, `tests/db`)

## Reading a call back

- Database timeline of a call (turns with timings, tool calls, searches, events, tickets, escalations): `poetry run relaypay-call` (latest), `--list`, `--call <id>`, `--schema test`.
- Backend log: `logs/backend.log` when `LOG_FILE=logs/backend.log` is in `.env` (fixed 01-10: the setting was never read before). Restart the backend after changing `.env`.
- Vapi's side (what it heard, its own latency): the save-calls PowerShell command writes `logs/vapi-calls.json`.

## How to run a test call

1. `.env` at the repo root (never read it; `.env.example` lists the names). Key values: `AGENT_MODEL=claude-haiku-4-5-20251001`, `LOG_LEVEL=DEBUG` for testing, `AGENT_TURN_TIMEOUT_SECONDS=15`, `LOG_FILE=logs/backend.log` (Claude reads this file instead of the user copying the terminal).
2. Terminal 1: `poetry run relaypay-backend` (look for "MCP server ready" and "Agent model: …").
3. Terminal 2: `ngrok http 8000` (static domain `latitude-mounting-empirical.ngrok-free.dev`).
4. Vapi dashboard → assistant "Precious – RelayPay Support" (id `475035be-518c-416b-ab01-2de46a8f3bd6`) → Talk to Assistant.
5. Save calls for review: the PowerShell "save-calls" command (Vapi API with `VAPI_PRIVATE_KEY` from `.env`, writes `logs/vapi-calls.json`, gitignored). The user runs it; Claude reads the file.

## Vapi setup (shared company org, so be careful)

- Custom LLM URL = the ngrok base URL. **Our secret goes in `model.headers["X-RelayPay-Secret"]`**, because the org-wide Custom LLM key always fills `Authorization` (and is visible to the org).
- `server.url` = `…/vapi/events`, same header; `serverMessages` = status-update, end-of-call-report.
- `endCallPhrases` = `goodbye` (one word; Vapi splits longer phrases). The model never says it: it writes `<end_call/>` and the backend says the goodbye.
- LiveKit endpointing, `waitSeconds` 0.6 (0.8 was tried on 01-10 and reverted: it didn't reduce early guesses), `stopSpeakingPlan.numWords` 2, voice `chunkPlan.minCharacters` 30 (the default; 10 split phrases).
- All changes are made with PowerShell PATCH commands the user runs; Claude never handles the private key.

**Phase 3 settings to apply (user runs this, from the repo root):** sends the pre-call form to `/chat/completions` (`metadataSendMode: "variable"`) and turns on Vapi's end-of-call summary. It reads the current model first and sends it back whole, so the URL and `X-RelayPay-Secret` header are kept.

```powershell
$key = ((Get-Content .env | Where-Object { $_ -match '^VAPI_PRIVATE_KEY=' }) -replace '^VAPI_PRIVATE_KEY=','').Trim()
$id = "475035be-518c-416b-ab01-2de46a8f3bd6"
$h = @{ Authorization = "Bearer $key"; "Content-Type" = "application/json" }
$a = Invoke-RestMethod -Uri "https://api.vapi.ai/assistant/$id" -Headers $h
$a.model | Add-Member -NotePropertyName metadataSendMode -NotePropertyValue "variable" -Force
$plan = if ($a.analysisPlan) { $a.analysisPlan } else { [pscustomobject]@{} }
$plan | Add-Member -NotePropertyName summaryPlan -NotePropertyValue @{ enabled = $true } -Force
$body = @{ model = $a.model; analysisPlan = $plan } | ConvertTo-Json -Depth 30
$r = Invoke-RestMethod -Method Patch -Uri "https://api.vapi.ai/assistant/$id" -Headers $h -Body $body
$r.model | Select-Object provider, url, metadataSendMode; $r.model.headers.PSObject.Properties.Name; $r.analysisPlan.summaryPlan
```

Expected: `metadataSendMode variable`, the header name `X-RelayPay-Secret` listed, `enabled True`. If Vapi rejects a field, nothing in the backend breaks: the form also arrives inside `call.assistantOverrides.metadata`, and without a summary `conversations.summary` stays empty.

## Lessons from today (the user cares about these)

- **Plan and explain before building.** Get an explicit "build" first. Show decision-log entries before adding them.
- **Lean tests:** one per behaviour that could break.
- **Guard in code** anything the caller must never hear (narration, reasoning); prompts alone weren't enough.
- **Measure before tuning:** the debug log (`Sent to Vapi`, engine steps) found the real causes each time.
- Commit to `main`; never push unless asked.

## Handover prompt (paste into the new session)

> I'm continuing my Koya Week 6 project: a RelayPay voice support agent. The repo is `customer-support-agent`. Read `CLAUDE.md`, then `docs/HANDOVER.md`, then the "▶ Next session" list at the top of `docs/BUILD_PLAN.md`, then `docs/SPECS.md`. Look through `src/` and `tests/` to confirm what exists, and run the tests. My decisions and reasons are in `../submission/REFLECTIONS_NOTES.md`, and the latency data is in `../submission/LATENCY_RESULTS.md`. Then tell me in a few lines where we are and what's next, and wait. Don't write code until I say so, and don't read my `.env`.


## Frontend handoff prompt (paste into the new session)

> I'm continuing my Koya Week 6 project: a RelayPay voice support agent. The repo is `customer-support-agent`. The backend is built and voice-tested; you're building the frontend. Read `CLAUDE.md`, then `docs/FRONTEND_PLAN.md` (the full plan: what's in and out of scope, the endpoints, migration, security rules, tests and build order), then `docs/HANDOVER.md` and `docs/SPECS.md` §3 and §6. The design is in `../design_handoff_relaypay_v1/` (its README is the spec) and the brand rules in `../RelayPay – Front-End Visual Brand Asset.md`. Run the tests first. Don't change the agent, tools or prompt. Don't read my `.env`, and never make real calls: I test by voice. Start with the voice page and form, explain each step briefly, and tell me when it's ready for a test call.
