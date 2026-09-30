# Handover: end of 29-09-2026

For the next Claude Code session. Read this, then `docs/BUILD_PLAN.md` ("▶ Next session"), then `docs/SPECS.md`.

## Where we are

- **Working end to end:** Vapi web call → ngrok → FastAPI `/chat/completions` → Claude Agent SDK (Haiku 4.5) → MCP server `relaypay` → `search_knowledge_base` (in-memory BM25 over the KB).
- **Built and committed:** KB search, MCP server (Streamable HTTP on 127.0.0.1:8001, bearer token), agent sessions (locked-down SDK options, one session per call), Vapi endpoint, `/vapi/events` webhook (prewarm on call start, close on call end), conversation flow (SPECS §2b), grounding prompt.
- **Built and tested, NOT yet voice-tested:** `<say>` tags (only text inside is spoken), a limit on waiting for a call's engine (15 s), prompt rules "never claim an action you can't do" and "never say where to find something unless the KB says so".
- **Supabase (Phase 2) done:** `poetry run relaypay-db` creates the 10 tables (`migrations/001_schema.sql`, RLS on, no policies) and upserts the seed data from `data/seed/`. Safe to re-run.
- **Not built yet:** the other 6 MCP tools (Phase 3), hardening (Phase 5), voice page (Phase 6), deploy (Phase 7), console (Phase 8), evaluations (Phase 9), submission docs (Phase 10).

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
- LiveKit endpointing, `waitSeconds` 0.6, `stopSpeakingPlan.numWords` 2, voice `chunkPlan.minCharacters` 30 (the default; 10 split phrases).
- All changes are made with PowerShell PATCH commands the user runs; Claude never handles the private key.

## Lessons from today (the user cares about these)

- **Plan and explain before building.** Get an explicit "build" first. Show decision-log entries before adding them.
- **Lean tests:** one per behaviour that could break.
- **Guard in code** anything the caller must never hear (narration, reasoning); prompts alone weren't enough.
- **Measure before tuning:** the debug log (`Sent to Vapi`, engine steps) found the real causes each time.
- Commit to `main`; never push unless asked.

## Handover prompt (paste into the new session)

> I'm continuing my Koya Week 6 project: a RelayPay voice support agent. The repo is `customer-support-agent`. Read `CLAUDE.md`, then `docs/HANDOVER.md`, then the "▶ Next session" list at the top of `docs/BUILD_PLAN.md`, then `docs/SPECS.md`. Look through `src/` and `tests/` to confirm what exists, and run the tests. My decisions and reasons are in `../submission/REFLECTIONS_NOTES.md`, and the latency data is in `../submission/LATENCY_RESULTS.md`. Then tell me in a few lines where we are and what's next, and wait. Don't write code until I say so, and don't read my `.env`.
