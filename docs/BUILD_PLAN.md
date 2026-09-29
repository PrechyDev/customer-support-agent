# Build Plan

Tick items as they're done (`[x]`). When something new comes up, add it to the right phase, not the bottom. Rules and behaviour live in `SPECS.md`, reasons in `../../submission/REFLECTIONS_NOTES.md`.

**Deadline: Friday 2 Oct 2026, 12:00pm.** Target 14/15.
**Order:** backend → voice interface → support console → evaluations and submission.

Last updated: 29-09-2026

---

## Phase 0: Planning docs
- [x] Business rules agreed and logged in the decisions log
- [x] `docs/SPECS.md`
- [x] `docs/BUILD_PLAN.md`
- [x] `docs/DESIGN.md` (brand baseline; mockups to add)
- [x] `.env.example`
- [x] `CLAUDE.md`

## Phase 1: Voice + KB latency test (the real components, KB only)
Goal: measure latency and accuracy by voice before building the rest.
- [ ] Add dependencies: `claude-agent-sdk`, `mcp`, `fastapi`, `uvicorn`, `python-dotenv` (done: `rank-bm25`, `snowballstemmer`, `pytest`)
- [x] Copy the KB into the repo at `data/relaypay-knowledge-base.md` (the reference folder isn't deployed)
- [ ] Check whether the Agent SDK bundles the Claude Code CLI (it isn't installed on this machine)
- [x] `kb/`: load the KB, split it into 37 chunks, BM25 + stemmer index, with unit tests
- [ ] `mcp_server/`: stdio server with `search_knowledge_base`, retrievals logged to a local file for now
- [ ] `agent/`: Agent SDK setup (model from env, MCP tools only, turn cap, short voice prompt with the 37 KB headings), one warm session per call
- [ ] `api/`: `POST /chat/completions`, auth header check, SSE streaming, per-turn timing log
- [ ] Vapi assistant set up (see Setup checklist), with ngrok running
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
- [ ] SQL migration: seed tables with status CHECK constraints
- [ ] SQL migration: runtime tables (SPECS §10)
- [ ] RLS on for every table, no anonymous policies
- [ ] Seed script, safe to re-run (upsert on IDs)
- [ ] Verify the row counts: 5 customers, 5 transactions, 3 payouts

## Phase 3: MCP tools
- [ ] `lookup_customer` (server-side email + company check, `found: false` on mismatch)
- [ ] `lookup_transaction` (status only, date rule, ID normalisation)
- [ ] `lookup_payout` (by payout or transaction ID, status only)
- [ ] `create_support_ticket` (idempotent, speakable ID)
- [ ] `create_escalation` (idempotent, linked ticket, call_booked rule, callback window Mon–Fri 08:00–18:00 UTC checked on the server)
- [ ] `log_conversation_event`
- [ ] Every tool writes to `tool_calls` and handles Supabase failures
- [ ] Unit tests per tool (missing records, mismatches, duplicates, DB down)

## Phase 4: Agent
- [ ] Full system prompt: response paths, verification flow, what can be said, escalation triggers, behaviour sections of the KB, callback hours + time zone confirmation, current UTC date/time
- [ ] Verification state stored on the conversation record
- [ ] Retrieval results written to `retrieval_logs`
- [ ] Turns written to `conversation_turns` (answer type, confidence note, timings)

## Phase 5: Backend hardening
- [ ] Spoken fallback line on a Claude error or timeout
- [ ] Logging after the response, errors caught
- [ ] Log-only phrase check
- [ ] Vapi end-of-call webhook: closes the conversation, `abandoned` if it never arrives
- [ ] Rate limiting on public endpoints
- [ ] Attempt limits (verification, repeated sensitive requests)

## Phase 6: Voice interface
- [ ] Voice page served by FastAPI, following `DESIGN.md`
- [ ] Vapi Web SDK with the public key only
- [ ] States: idle, connecting, listening, agent speaking, ended, mic denied, error
- [ ] Works on mobile width

## Phase 7: Deploy (see Deployment guide)
- [ ] Dockerfile
- [ ] Secrets in Secret Manager
- [ ] Cloud Run deploy with min instances 1
- [ ] Vapi Custom LLM URL switched from ngrok to Cloud Run
- [ ] Link opens from another device or an incognito window

## Phase 8: Support console
- [ ] Add the Claude Design mockup to `DESIGN.md`
- [ ] Login (at least one shared login)
- [ ] Recent conversations and their status
- [ ] Escalation count and list, with the collected contact details
- [ ] Customers and their calls

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

1. **Container:** Python 3.12 slim image, Poetry install without dev dependencies, runs `uvicorn`. If the Agent SDK needs the Claude Code CLI and doesn't bundle it, add Node and the CLI to the image *(verify)*.
2. **Secrets:** create each one in Secret Manager (`ANTHROPIC_API_KEY`, `DATABASE_URL`, `VAPI_LLM_SECRET`, console login) and mount them as env variables. Never bake them into the image.
3. **Deploy:** `gcloud run deploy relaypay-support --source . --region europe-west1 --min-instances 1 --set-secrets ...` *(verify flags)*.
   - **min instances 1:** no cold start at the beginning of a call. The cost trade-off is recorded in the reflections.
   - **Request timeout:** long enough for a streamed turn.
   - **Concurrency:** kept low, because each call runs its own agent and MCP subprocesses.
4. **Region:** `europe-west1` (Belgium), the closest Google region to Supabase's `eu-west-1` (Ireland).
5. **Vapi:** update the assistant's Custom LLM URL to the Cloud Run URL.
6. **Smoke test:** open the voice page in incognito on another device, run one KB question and one lookup, then check the Supabase rows.
7. **Keep it live** until grading is done. Check the link again after submitting.
