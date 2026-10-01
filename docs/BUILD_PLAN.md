# Build Plan

Tick items as they're done (`[x]`). When something new comes up, add it to the right phase, not the bottom. Rules and behaviour live in `SPECS.md`, reasons in `../../submission/REFLECTIONS_NOTES.md`.

**Deadline: Friday 2 Oct 2026, 12:00pm.** Target 14/15.
**Order:** backend → voice interface → support console → evaluations and submission.

Last updated: 01-10-2026

---

## ▶ Next session (start here): 01-10-2026 (frontend)

State: **backend done and voice-tested** (Phase 3 + fixes from 4 voice calls, commits `d63989b`, `322e9b7`). 112 tests pass.
**The frontend is handed to a new session: follow `docs/FRONTEND_PLAN.md`** (scope in/out, endpoints, migration 005,
security rules, tests, build order). Design source: `../design_handoff_relaypay_v1/` (README is the spec).

1. [x] Voice page + pre-call form + live captions + greeting by name + outcome box + rating (FRONTEND_PLAN §3–§5.1). Built 01-10; migration 005 to apply
2. [ ] User test call through the page: form data reaches the call record (`relaypay-call`)
3. [ ] Console: sign-in, Dashboard, Cases (resolve with note), Conversations, Customers, new-item ping (§3, §5.2–§5.3)
4. [ ] Deploy (Phase 7), then the 9 test scenarios by voice (combined into ~3 calls), evidence, Loom, reflections, one-pager
5. [ ] Open from earlier: model decision note, `docs/vapi-assistant.json`, Vapi `waitSeconds` 0.8 (optional)

## Phase 0: Planning docs
- [x] Business rules agreed and logged in the decisions log
- [x] `docs/SPECS.md`
- [x] `docs/BUILD_PLAN.md`
- [x] `docs/DESIGN.md` (brand baseline; mockups to add)
- [x] `.env.example`
- [x] `CLAUDE.md`

## Phase 1: Voice + KB latency test (the real components, KB only)
Goal: measure latency and accuracy by voice before building the rest.
- [x] Add dependencies: `rank-bm25`, `snowballstemmer`, `pytest`, `mcp` (v2), `claude-agent-sdk`, `uvicorn`, `python-dotenv`
- [x] Add `fastapi`
- [x] Copy the KB into the repo at `data/relaypay-knowledge-base.md` (the reference folder isn't deployed)
- [x] Check whether the Agent SDK bundles the Claude Code CLI: **it doesn't on Windows** (`_bundled/` is empty)
- [x] Install the **native** Claude Code on Windows: `irm https://claude.ai/install.ps1 | iex`. The SDK finds `~/.local/bin/claude.exe` itself (verified). On Linux/Cloud Run the SDK wheel bundles Claude Code, so nothing to install
- [x] `kb/`: load the KB, split it into 37 chunks, BM25 + stemmer index, with unit tests
- [x] `mcp_server/`: Streamable HTTP on 127.0.0.1:8001, bearer token, `X-Conversation-Id` header, `search_knowledge_base`, retrievals logged to `logs/retrieval.jsonl`, tests incl. end-to-end over HTTP
- [ ] Generate `MCP_AUTH_TOKEN` and add it to `.env`
- [x] `agent/`: prompt (37 headings, KB policy sections, date), locked-down SDK options, one session per call with per-call lock, 30 s turn timeout, fallback lines, idle cleanup (180 s), 10-call cap, tests with a fake client (suite trimmed to 50 lean tests)
- [x] `api/`: `POST /chat/completions` (Vapi secret, OpenAI SSE streaming, non-stream fallback, barge-in interrupts the engine, per-turn latency log), `/health`, one start command `poetry run relaypay-backend` (MCP first, then public app)
- [ ] Vapi assistant set up (see Setup checklist), with ngrok running
- [ ] Vapi `endCallPhrases: ["goodbye"]` (one word, can't be split) and voice `chunkPlan.minCharacters` back to 30
- [ ] Vapi silence hooks: 60 s "are you still there" message, 120 s goodbye + endCall, reset on caller speech (save in `docs/vapi-assistant.json`)
- [x] First voice calls (Haiku 4.5): calls work end to end. Found: invented details, unusable questions (loops), answering before searching, spoken reasoning, no goodbye, pointless filler, dropped words
- [x] Fixes: grounding prompt rewrite, FAQ question match in search, goodbye phrase, backend filler after 2 s, debug log of the exact text sent to Vapi
- [x] **Conversation flow (SPECS §2b):** drain interrupted turns · complete messages (drop narration) · empty reply from spoken text · waiting ladder 2 s / 8 s / 15 s · warm closing line · realistic shared-stream fake engine in tests
- [ ] Vapi: LiveKit endpointing, `waitSeconds` 0.6, `stopSpeakingPlan.numWords` 2
- [x] Latency fixes: sentence streaming after a tool, call-started prewarm + end-of-call close via `/vapi/events`. Filler removed after testing; one reassurance at 10 s. Prompt: one clear next step per reply
- [ ] Vapi: `server.url` = `/vapi/events` with `X-RelayPay-Secret`, `serverMessages` = status-update + end-of-call-report
- [ ] Re-run the two failing conversations with LOG_LEVEL=DEBUG; compare "Sent to Vapi" with Vapi's transcript word by word
- [ ] Voice test: Haiku 4.5
- [ ] Voice test: Sonnet 5
- [ ] Results and model decision in `submission/LATENCY_RESULTS.md`, plus the model choice in the reflections notes

**Test script (the same questions on every call):**
1. "What fees does RelayPay charge for international payments?"
2. "Can RelayPay guarantee my payout arrives by 9am tomorrow?"
3. "My payment is stuck." (should ask a clarifying question)

**Recorded per turn:** cold or warm, time to first text, total time, chunks used, pass or fail.

## Phase 2: Supabase
- [x] Decide on DB access: `psycopg` + session pooler `DATABASE_URL`
- [x] SQL migration: seed tables with status CHECK constraints (`migrations/001_schema.sql`)
- [x] SQL migration: runtime tables (SPECS §10), speakable IDs T-1001 / E-1001, one-ticket-per-(conversation, category, reference)
- [x] RLS on for every table, no policies (verified: 10 tables, RLS on, 0 policies)
- [x] Seed script, safe to re-run (upsert on IDs): `poetry run relaypay-db` (rows validated before connecting)
- [x] Verify the row counts: 5 customers, 5 transactions, 3 payouts (ran twice: same counts)

## Phase 3: MCP tools
- [x] `lookup_customer` (server-side email + company check, `found: false` on mismatch)
- [x] `lookup_transaction` (status only, date rule, ID normalisation)
- [x] `lookup_payout` (by payout or transaction ID, status only)
- [x] `create_support_ticket` (idempotent, speakable ID)
- [x] `create_escalation` (idempotent, linked ticket, call_booked rule, callback window: city or time zone → zoneinfo, trimmed to Mon–Fri 08:00–18:00 UTC, returned in local time)
- [x] `log_conversation_event`
- [x] Every tool writes to `tool_calls` and handles Supabase failures
- [x] Add `tzdata` (Windows and slim containers have no time zone database)
- [x] Unit tests per tool (missing records, mismatches, duplicates, DB down, callback windows: partly/fully outside hours, weekend, DST, unknown time zone)

- [x] Every escalation creates or links a ticket and logs `escalation_created` (one statement); caps 2 verifications / 3 tickets / 2 escalations
- [x] Fewer database round trips per tool (upsert returns the row, one list query per call, escalation + event in one statement): ticket 1.1 s → 0.45 s, escalation 1.1 s → 0.8 s on the session pooler
- [x] Real-Supabase smoke test of all tools over MCP HTTP (no model, no Vapi), rows cleaned up

## Phase 4: Agent
- [x] Full system prompt: response paths, verification flow, what can be said, escalation triggers, behaviour sections of the KB, callback hours in local time only (ask city or time zone, never mention UTC), current date/time
- [x] Verification state stored on the conversation record
- [x] Retrieval results written to `retrieval_logs`
- [x] Turns written to `conversation_turns` (answer type, confidence note, timings)

- [x] `<say type sources>` labels; backend grounding check writes the confidence note ("NOT GROUNDED" flagged)
- [x] Pre-call form (Vapi metadata) read by the backend: stored on the conversation, in the prompt as unverified contact details, used for escalations
- [x] All 7 tools allowed in the SDK options (and nothing else)
- [x] Pre-call form text never reaches the model (prompt shows only which fields were filled; tools read the values)
- [x] Out of credit / bad API key ends the call at once (ERROR logged); second turn-limit hit escalates automatically
- [x] Throwaway `test` schema (own ticket numbers) for smoke tests; real counters reset to T-1001 / E-1001
- [x] Removed the unused `main.py` placeholder
- [x] Review fixes: per-call lock can't be dropped while a tool waits; 2,000-character message cap; a repeated verification pair isn't counted (migration 003, applied to public and test); real-database tests for the SQL (`tests/db/test_repository_integration.py`)
- [x] Voice-test fixes (TXN-9001 call): callback flow (call back or email; day, time, city, phone with country code, read back), email read-back, reference on the escalation's ticket, `caller_verified` on tickets, reference-guessing guard (3 misses), no reference-format hint, no ghost turns, escalation categories in the tool description (migration 004 on public and test)
- [x] `relaypay-call` reads a call back from the database; `LOG_FILE` is now actually read

## Phase 5: Backend hardening
- [x] Spoken fallback line on a Claude error or timeout
- [x] Logging after the response, errors caught
- [x] Log-only phrase check (flags go in the turn's confidence note)
- [x] Vapi end-of-call webhook: closes the agent session and the conversation record (Vapi's summary, final status), `abandoned` if it never arrives (idle cleanup)
- [x] Vapi call-started webhook: start the agent session while the greeting plays (built early, with the latency fixes)
- [ ] Rate limiting on public endpoints
- [x] Attempt limits (verification, repeated sensitive requests)

## Phase 6: Voice interface (plan: `docs/FRONTEND_PLAN.md`)
- [x] Voice page served by FastAPI, following the handoff, with the pre-call form (name, email required; company and phone optional) sent as Vapi call metadata `{name, email, company, phone}`
- [x] Vapi Web SDK (`@vapi-ai/web@2.7.1`, pinned) with the public key only (`GET /voice/config`)
- [x] States: idle, connecting, listening, agent speaking, "one moment", muted, ended, mic denied, connection error
- [x] Works on mobile width (checked at 320 and 1440 px, keyboard order checked)
- [x] Live captions, greeting by first name (`variableValues.name`), outcome box + rating (`/voice/calls/{id}/outcome`, `/rating`), migration 005
- [ ] User applies migration 005 + `.env` values + Vapi first message (FRONTEND_PLAN §6–§7), then test call #1 through the page

## Phase 7: Deploy (see Deployment guide)
- [ ] Dockerfile
- [ ] Secrets in Secret Manager
- [ ] Cloud Run deploy with min instances 1
- [ ] Vapi Custom LLM URL switched from ngrok to Cloud Run
- [ ] Link opens from another device or an incognito window

## Phase 8: Support console (plan: `docs/FRONTEND_PLAN.md`; roles, assignment and analytics are out of scope)
- [ ] Add the Claude Design mockup to `DESIGN.md`
- [ ] Login (at least one shared login)
- [ ] Recent conversations and their status
- [ ] Escalation count and list, with the collected contact details
- [ ] Customers and their calls
- [ ] New ticket/escalation ping: poll every 30s, sound + badge, "Enable sound" button, no repeat pings after refresh

## Phase 9: Evaluations
- [ ] Evaluation runner that writes to `evaluations`
- [ ] 9 scenarios + injection + CUS-1003 note + delayed + verification failure (SPECS §12)
- [ ] Voice run of every scenario, with Supabase records that match

## Phase 10: Submission
- [ ] Testing evidence table (`submission/TESTING_EVIDENCE.md`)
- [ ] One-pager
- [ ] Reflection answers from the notes
- [ ] README with setup instructions a grader can follow
- [ ] Secret scan of the repo, including git history
- [ ] Loom (5–8 min), with audio checked
- [ ] `submission/SUBMISSION_CHECKLIST.md` all ticked

## After grading (cleanup)
- [ ] Rotate `VAPI_LLM_SECRET`: it's attached to the assistant as an assistant-level Custom LLM credential, which is **visible in the assistant JSON to everyone in the shared Vapi org**. Generate a new one, update `.env`, and re-run the credential PATCH.
- [ ] Rotate `MCP_AUTH_TOKEN` and the Vapi private key if they were ever shown on screen

---

## Setup checklist (accounts, keys, tools)

| Item | Where | Status |
|---|---|---|
| Anthropic API key | console.anthropic.com → `.env` | [x] in `.env` |
| Supabase project | supabase.com → Connect → **Session pooler** string into `.env` as `DATABASE_URL` (region eu-west-1) | [ ] |
| Vapi account | dashboard.vapi.ai | [x] account exists (**shared cohort org**) |
| Vapi naming | prefix everything with my name: `precious-relaypay-llm-secret`, "Precious – RelayPay Support" | [ ] |
| Vapi config backup | export the assistant config to `docs/vapi-assistant.json` (no secrets) so it can be recreated in minutes | [ ] |
| Vapi org for grading | ask the instructor whether the graded assistant can live in my own Vapi account (shared credits or edits could break the live link) | [ ] |
| MCP auth token | generate a random string → `MCP_AUTH_TOKEN` in `.env` | [ ] |
| Vapi Custom LLM secret | generate a random string → Vapi credential + `VAPI_LLM_SECRET` in `.env` | [ ] |
| Vapi public key + assistant ID | Vapi dashboard → `.env` (for the voice page) | [ ] |
| Vapi private key (optional) | to pull call logs and latency | [ ] |
| ngrok auth token | `ngrok config add-authtoken <token>`; claim the free static domain if available | [ ] |
| Google Cloud project + billing | console.cloud.google.com | [ ] |
| `gcloud` CLI | not installed on this machine: install Google Cloud SDK | [ ] |
| Local `.env` location | the app reads `.env` at the **repo root** (gitignored). The current one is at `Week 6/.env`, so move or copy it | [ ] |

### Vapi assistant (Phase 1)
1. Assistants → Create → Blank. Name: "RelayPay Support (test)".
2. Model → Provider **Custom LLM**. URL = the ngrok (later Cloud Run) base URL; Vapi appends `/chat/completions` (confirm in the first call's logs). Model name: `relaypay-agent` (the backend chooses the real model).
3. First message: "Hi, this is RelayPay support. How can I help you today?"
4. Credential: a custom credential holding `VAPI_LLM_SECRET`, sent in the `Authorization` header.
5. Transcriber and voice: defaults for now.
6. Test with "Talk to Assistant".

---

## Deployment guide (Cloud Run)

Items marked *(verify)* get confirmed when we reach Phase 7.

1. **Container:** `python:3.12-slim` (Debian, glibc), Poetry install without dev dependencies, runs `relaypay-backend` with `HOST=0.0.0.0`. **No Claude Code install needed:** the SDK's Linux wheel (`manylinux_2_17_x86_64`, in `poetry.lock`) bundles it. Run as a non-root user with a writable home and `/tmp` (the agent's working and config folders live there).
   - **Sizing (Agent SDK hosting docs):** about **1 GiB RAM and 1 CPU per concurrent agent session**. Set `AGENT_MAX_SESSIONS` to what the instance can hold, e.g. 4 GiB / 2 vCPU → `AGENT_MAX_SESSIONS=3`. Note that Cloud Run's `/tmp` is in memory, so it counts toward RAM.
   - **One instance only (`--max-instances 1`), required:** the per-call lock that keeps verification, ticket and escalation caps safe lives in memory, and so does each call's agent session. A second instance wouldn't have it, so a caller whose next message landed there would lose the conversation. Scaling out later needs a `SessionStore` (hosting docs, "hybrid sessions") or session pinning.
2. **Secrets:** create each one in Secret Manager (`ANTHROPIC_API_KEY`, `DATABASE_URL`, `VAPI_LLM_SECRET`, console login) and mount them as env variables. Never bake them into the image.
3. **Deploy:** `gcloud run deploy relaypay-support --source . --region europe-west1 --min-instances 1 --set-secrets ...` *(verify flags)*.
   - **min instances 1:** no cold start at the beginning of a call. The cost trade-off is recorded in the reflections.
   - **Request timeout:** long enough for a streamed turn.
   - **Concurrency:** kept low, because each call runs its own agent and MCP subprocesses.
4. **Region:** `europe-west1` (Belgium), the closest Google region to Supabase's `eu-west-1` (Ireland).
5. **Vapi:** update the assistant's Custom LLM URL to the Cloud Run URL.
6. **Smoke test:** open the voice page in incognito on another device, run one KB question and one lookup, then check the Supabase rows.
7. **Keep it live** until grading is done. Check the link again after submitting.
