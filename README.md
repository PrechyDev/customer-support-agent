# RelayPay Voice Support Agent

A voice customer support agent for RelayPay, a B2B cross-border payments company. Customers talk to the assistant,
**Bex**, in the browser. Bex answers from an approved knowledge base, looks up accounts, transactions and payouts
through a dedicated **MCP server**, opens tickets and escalations when a person is needed, and records every step in
Postgres (Supabase). Support staff pick up the work in a web **support console**.

- **Voice page (live):** https://relaypay-support-803943652745.europe-west1.run.app/
- **Support console (live):** https://relaypay-support-803943652745.europe-west1.run.app/console (you can reach out for test credentials)
- **MCP demo endpoint (live, test data):** https://relaypay-mcp-demo-1-803943652745.europe-west1.run.app/mcp (see *Using the MCP server on its own*)

## Features

**Voice assistant**
- Answers only from the approved knowledge base. Every reply names the knowledge base sections it used, and the
  backend checks them; anything it can't back up is flagged `NOT GROUNDED` for review.
- Four response paths: answer, ask a clarifying question, hand over to a specialist, or decline politely.
- Looks up a customer (email and company, two attempts per call), a transaction or a payout. Callers hear the status
  only, never amounts or internal reasons.
- Opens a **ticket** for a problem the team must fix, and an **escalation** when a specialist must contact the caller
  (by phone or email, with a callback window converted to the caller's time zone). Every escalation is linked to a
  ticket.
- Delayed, failed or under-review payments and restricted accounts are escalated by the lookup itself, not left to
  the model.
- Natural turn-taking: interruptions, pauses and "um"s are handled, and the backend speaks the closing line.

**Voice page**
- A short pre-call form (name and email; company and phone optional), so callers aren't asked again.
- A ringing tone while connecting, live captions, mute, and a clear message if the microphone is blocked.
- After the call: what happens next (callback window, email follow-up or ticket reference) and a "Did this help?"
  rating.

**Support console**
- Personal accounts with three roles (owner, admin, support) and copy-link invites; no email service needed.
- Dashboard: today's numbers, what needs attention first (callbacks due today, unassigned cases) and recent calls.
- One Cases list for escalations and tickets: take, assign, resolve with a note, reopen, internal notes and a
  timeline.
- Conversations with full transcripts, what the assistant did, and the grounding check of each reply.
- Customer profiles, analytics over any date range, paging on long lists, and a chime when new cases arrive.

**Records and quality**
- Every call, turn (with timings), tool call, knowledge base search, event, ticket and escalation is stored.
- `relaypay-eval` runs 13 scripted scenarios through the real system and scores them from the stored records.

## How it works

```
Browser (voice page)                      Support staff (console)
   │ Vapi Web SDK, public key only            │ signed session cookie
   ▼                                          ▼
Vapi (speech ↔ text) ──► FastAPI backend (Cloud Run) ──────────────────────► Supabase Postgres
   POST /chat/completions │  OpenAI-format SSE, shared secret                (all records, RLS on)
   POST /vapi/events      │
                          ▼
              Claude Agent SDK (Haiku 4.5): one session per call,
              limited to the support tools (no files, shell or web)
                          │ MCP over Streamable HTTP, bearer token
                          ▼
              MCP server "relaypay" on 127.0.0.1, inside the same container
              7 tools: knowledge base search (in-memory BM25) + account, ticket, escalation and event tools
```

Vapi handles speech only; it is configured as a **Custom LLM**, so all support logic runs in the backend. Business
rules live **in the tools**, not just in the prompt: identity verification, what a caller may hear, limits per call,
and escalating a status that needs a person. Only text the model writes inside `<say>` tags is spoken.

| Layer | Technology |
|---|---|
| Speech | Vapi (web calls, Custom LLM) |
| Backend | Python 3.12, FastAPI, Uvicorn |
| Agent | Claude Agent SDK |
| Tools | MCP server (MCP Python SDK, Streamable HTTP) |
| Retrieval | BM25 with stemming, in memory |
| Data | Supabase Postgres via psycopg |
| Frontend | Plain HTML, CSS and JavaScript (no build step) |
| Hosting | Google Cloud Run |

## Getting started

**Prerequisites:** Python 3.12, [Poetry](https://python-poetry.org/) 2.x, a Supabase project (the free tier works)
and an Anthropic API key. A Vapi account is only needed for voice calls.

```bash
poetry install
cp .env.example .env          # fill in the values; each setting is explained in the file
poetry run relaypay-db        # creates the tables and loads the seed data (safe to re-run)
poetry run pytest -q          # the test suite runs offline; RUN_DB_TESTS=1 adds the database tests
poetry run relaypay-backend   # app on http://127.0.0.1:8000, MCP server on http://127.0.0.1:8001
```

- `DATABASE_URL` is the Supabase **session pooler** connection string.
- `DATABASE_SCHEMA=test` uses a separate, throwaway set of tables. Create it once with
  `DATABASE_SCHEMA=test poetry run relaypay-db`.

### Voice calls on a local machine

1. Expose port 8000, for example with `ngrok http 8000`.
2. In Vapi, set the assistant's model to **Custom LLM** with the URL `https://<your-tunnel>` and the header
   `X-RelayPay-Secret: <VAPI_LLM_SECRET>`.
3. Set the assistant's server URL to `https://<your-tunnel>/vapi/events`, with the same header.
4. Put the assistant ID and Vapi's **public** key in `.env`, restart the backend and open `http://127.0.0.1:8000/`.

### Support console

Set `CONSOLE_SESSION_SECRET` in `.env`, then create the owner account. The command prints a one-time setup link
(valid for 72 hours) where the owner sets a name and password:

```bash
poetry run relaypay-admin --email owner@example.com
```

The owner can then invite admins and support staff from the console's Team page.

## Useful commands

| Command | What it does |
|---|---|
| `poetry run relaypay-backend` | Starts the app and the MCP server |
| `poetry run relaypay-db` | Applies the migrations and loads the seed data |
| `poetry run relaypay-admin --email …` | Creates the console owner (`--reset` issues a new link) |
| `poetry run relaypay-call [--call <id>]` | Prints a call's full record: turns, tool calls, searches, cases |
| `poetry run relaypay-eval` | Runs the evaluation scenarios |
| `poetry run relaypay-mcp` | Runs the MCP server on its own |
| `poetry run pytest -q` | Runs the tests |

## Using the MCP server on its own

The MCP server runs inside the backend, and it can also run alone, for example to explore the tools. In production it
listens only on localhost inside the container, so the tools are never reachable from the internet.

**Quickest, nothing to install: the demo endpoint.** A separate demo copy of the MCP server runs on Cloud Run against
**test data only** (the brief's seed customers, transactions and payouts; never real records). Its token is shared
with the project submission, and it opens only this demo service, never the production one.

- URL: `https://relaypay-mcp-demo-1-803943652745.europe-west1.run.app/mcp`
- Header: `Authorization: Bearer <demo-token>`

```bash
# macOS / Linux: list the 7 tools
curl -s https://relaypay-mcp-demo-1-803943652745.europe-west1.run.app/mcp -H "Authorization: Bearer <demo-token>" \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

```powershell
# Windows PowerShell: look up a transaction (any tool works the same way)
$h = @{ Authorization = "Bearer <demo-token>"; Accept = "application/json, text/event-stream"; "X-Conversation-Id" = "grader-1" }
$b = '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"lookup_transaction","arguments":{"transaction_id":"TXN-9001"}}}'
(Invoke-RestMethod -Uri https://relaypay-mcp-demo-1-803943652745.europe-west1.run.app/mcp -Method Post -Headers $h -ContentType "application/json" -Body $b).result.content.text
```

Things to try: `search_knowledge_base` with `{"query": "transfer fees"}`; `lookup_payout` with `{"payout_id": "PAY-7002"}`;
`lookup_customer` with `{"email": "amara@lagosledger.example", "company_name": "LagosLedger"}`, which first returns
`confirm_email` (the read-back a caller hears); send the same call again with `"email_confirmed": true` to verify.
Use your own `X-Conversation-Id` (any short name): verification, caps and created tickets belong to that conversation.
A request without the token gets `401`. The MCP Inspector (`npx @modelcontextprotocol/inspector`, transport
**Streamable HTTP**, the URL and header above) works too.

**Run it yourself with Docker (no Python or keys needed):**

```bash
docker build -t relaypay-support .
docker run --rm -p 8001:8001 -e MCP_HOST=0.0.0.0 \
  -e MCP_AUTH_TOKEN=replace-with-a-32-character-token relaypay-support relaypay-mcp
# serves http://127.0.0.1:8001/mcp; check it in 10 seconds:
curl -s http://127.0.0.1:8001/mcp -H "Authorization: Bearer replace-with-a-32-character-token" \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

On Windows PowerShell, use `Invoke-RestMethod` as in the demo example above, with `http://127.0.0.1:8001/mcp` and this
token (PowerShell 5.1 mangles quotes passed to `curl.exe`).

**With Python:**

```bash
# MCP_AUTH_TOKEN: any string of 32 or more characters. DATABASE_URL is optional: without it,
# search_knowledge_base works and the account tools answer "unavailable".
MCP_AUTH_TOKEN=<32+ characters> poetry run relaypay-mcp      # http://127.0.0.1:8001/mcp
```

On Windows PowerShell: `$env:MCP_AUTH_TOKEN="<32+ characters>"; poetry run relaypay-mcp`.

**MCP Inspector:** run `npx @modelcontextprotocol/inspector` and choose transport **Streamable HTTP**, URL
`http://127.0.0.1:8001/mcp` and the header `Authorization: Bearer <token>`. Optionally add `X-Conversation-Id: demo-1`
to group calls into one conversation. List the tools and call `search_knowledge_base` with
`{"query": "transfer fees"}`.

**curl:**

```bash
curl -s http://127.0.0.1:8001/mcp -H "Authorization: Bearer <token>" -H "X-Conversation-Id: demo-1" \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"search_knowledge_base","arguments":{"query":"transfer fees"}}}'
```

| Tool | What it does |
|---|---|
| `search_knowledge_base` | BM25 search over the knowledge base; returns sections with IDs and scores; every search is logged |
| `lookup_customer` | Verifies email and company (two attempts per call); returns plan and statuses only |
| `lookup_transaction` | Status of a transaction from its reference; escalates or opens a ticket itself when people are needed |
| `lookup_payout` | The same for payouts |
| `create_support_ticket` | Logs a problem; repeat requests return the same ticket; at most 3 per call |
| `create_escalation` | Hands the caller to a specialist with a linked ticket and their contact choice; at most 2 per call |
| `log_conversation_event` | Records judgement calls such as a sensitive request, an injection attempt or frustration |

Requests without the right bearer token get `401`. The conversation comes from the `X-Conversation-Id` header, which
the backend sets for each call; the model can never choose it. The account tools need `DATABASE_URL` pointing at a
database prepared with `relaypay-db`. End-to-end tests over HTTP: `poetry run pytest tests/mcp_server`.

## Evaluations

The evaluation suite runs 13 scenarios, covering everyday questions, lookups, tickets and escalations, a prompt
injection, a restricted account, failed verification and a topic the knowledge base doesn't cover. Run it against a
backend that uses the test schema (port 8100 here, to keep a normal backend free):

```bash
DATABASE_SCHEMA=test PORT=8100 MCP_PORT=8101 poetry run relaypay-backend      # terminal 1
DATABASE_SCHEMA=test poetry run relaypay-eval --base-url http://127.0.0.1:8100  # terminal 2
```

Each scenario is sent as text in Vapi's request format through the real agent, tools and database. It is scored from
the records it leaves, never from the model's own account of what it did, and saved to the `evaluations` table.
Evaluations refuse to run on the `public` schema, so they never mix with real records. A real voice call can be
scored the same way:

```bash
poetry run relaypay-eval --call <vapi-call-id> --scenario s4_transaction --schema public
```

## Project structure

```
src/customer_support_agent/
  mcp_server/    MCP server and its 7 tools (tools/accounts.py, cases.py, knowledge.py)
  agent/         Agent SDK sessions, system prompt, grounding check, stop hook
  api/           FastAPI app: Vapi endpoint and webhook, voice page API, console API, call records
  console/       console security (passwords, sessions), roles and views
  db/            Postgres access (repository.py, console_store.py) and command-line tools
  domain/        pure rules: statuses, callback windows, normalising spoken input
  kb/            knowledge base chunking and BM25 search
  evals/         evaluation scenarios, scoring and runner
  web/static/    voice page and support console
data/            knowledge base and seed data
migrations/      SQL migrations, applied in order by relaypay-db
tests/           pytest, mirroring src/
docs/            business rules, build plan, console API and design notes
```

## Deployment

The `Dockerfile` builds one container that runs the app and the MCP server together. Secrets are read from the
environment at runtime. For deploying to Google Cloud Run, see `docs/DEPLOYMENT.md`.

## Security

- Secrets live only in environment variables (Secret Manager in production). `.env` is never committed or copied into
  the image.
- The browser only ever receives Vapi's **public** key. `/chat/completions` and `/vapi/events` require a shared secret.
- The MCP server binds to localhost and requires a bearer token.
- Supabase has Row Level Security on every table with no policies, so its public API can read nothing; the app connects
  to Postgres directly.
- Console: scrypt password hashes, one-time links stored only as hashes, an HttpOnly SameSite=Strict session cookie, a
  CSRF header on every change, sign-in rate limits, and roles checked on the server.
- Everything callers say, every tool result and all knowledge base text is treated as data, never as instructions.
- All text in the voice page and console is inserted as text, never as HTML.

## Documentation

| Document | Contents |
|---|---|
| `docs/SPECS.md` | Business rules and the reasons behind them |
| `docs/CONSOLE_API.md` | The support console's API, roles and paging |
| `docs/DESIGN.md` | Design tokens and the voice page and console as built |
| `docs/DEPLOYMENT.md` | Deploying to Google Cloud Run |
| `docs/BUILD_PLAN.md` | Build phases and checklist |
| `.env.example` | Every setting, with an explanation |
