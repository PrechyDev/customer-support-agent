# Frontend build plan: voice page + support console

> **Console update 01-10-2026:** the console's sign-in and data endpoints are now defined in `docs/CONSOLE_API.md`
> (per-person accounts with roles, invites, case ownership, analytics). Where this plan says one shared login
> (`CONSOLE_EMAIL` / `CONSOLE_PASSWORD`, §5.2–§5.3), CONSOLE_API.md replaces it.

Written 01-10-2026 for the session that builds the frontend. The backend (agent, MCP tools, Supabase records) is
built and tested: **don't change it** beyond the thin endpoints listed in §5 and the migration in §6.

**Deadline: Friday 2 Oct 2026, 12:00.** Build the voice page first, then the console.

---

## 0. Before you start

1. Read `CLAUDE.md` (how the user works: explain, small pieces, lean tests, commit on `main` only when asked,
   **never read `.env`**). Then `docs/HANDOVER.md`, `docs/SPECS.md` (§3 form, §6 escalations and callbacks), and
   this file.
2. Design sources, in this order of authority:
   - `../design_handoff_relaypay_v1/README.md`: **the spec** (tokens, layout, copy, behaviour). High fidelity.
   - `../design_handoff_relaypay_v1/Voice Support.dc.html` and `Support Console.dc.html`: clickable references.
     Open in a browser with `support.js` and `assets/` next to them. Don't ship `support.js`.
   - `../RelayPay – Front-End Visual Brand Asset.md`: the brand rules (checked: the handoff follows them).
   - `docs/DESIGN.md`: older notes. **Where it disagrees with the handoff, the handoff wins**; update DESIGN.md's
     colour tokens to the handoff's (§2 below) as part of this work.
3. Run the tests first: `poetry run pytest -q` (all should pass).
4. **Claude never makes real calls.** The user tests by voice.

---

## 1. Decisions already made (don't reopen)

| Decision | Why |
|---|---|
| **Plain HTML + CSS + JS, served by the FastAPI backend.** No Next.js/React/Tailwind, no build step | One service, one deploy (Cloud Run), no second app to host today. The look is recreated exactly from the handoff tokens |
| **The browser never talks to Supabase.** It calls our backend's endpoints only | No database keys in the browser; the backend already enforces the data rules |
| **Only Vapi's public key reaches the browser**, via `GET /voice/config` | CLAUDE.md hard rule |
| Vapi Web SDK **`@vapi-ai/web@2.7.1`**, pinned, from `https://cdn.jsdelivr.net/npm/@vapi-ai/web@2.7.1/+esm` (check the URL loads; if not, use the package's UMD build from jsDelivr, still pinned) | No bundler |
| **Pre-call form, required name + email, optional company + phone** | SPECS §3. Contact details only, never proof of identity. The backend keeps the typed text away from the model |
| **Greet by name** | The user asked. First name only, via Vapi `variableValues` |
| **Live captions on by default** | The user needs to read the call; also accessibility |
| One shared console login from `.env` | No time for per-person accounts and roles today |

---

## 2. Design tokens (from the handoff; replace DESIGN.md's)

Font Inter (`https://rsms.me/inter/inter.css`), fallback `system-ui, -apple-system, "Segoe UI", sans-serif`.
Colours: ink `#0F1B2D`, ink-2 `#5A6475`, ink-3 `#6B7483`, ink-4 `#8A93A1`, brand `#0E3476` (hover `#0A2860`),
teal `#1683AC`, page `#F5F6F8`, surface `#FFFFFF`, subtle `#FAFBFC`, border `#E3E6EB`, border-input `#D5DAE1`,
divider `#EDEFF2`, row-hover `#F7F9FB`, nav-active `#E8EEF8`, danger `#B42318` (hover `#912018`).
Status badges (bg/fg): green `#EAF5EC/#1E6B34`, blue `#E8EEF8/#0E3476`, teal `#E6F3F8/#0E5E7E`,
amber `#FBF1E1/#8A5300`, red `#FBEAE8/#A3261B`, grey `#F1F3F6/#4A5465`.
No shadows, no gradients, no emoji. Radius, spacing, type scale and motion: handoff README "Design Tokens".
Put them in one `tokens.css` as CSS custom properties; never hard-code a colour twice.

Logo: copy `../design_handoff_relaypay_v1/assets/relaypay-logo-cropped.png` into the app's static folder.

---

## 3. Scope

### Voice page: IN

| # | Feature | Notes |
|---|---|---|
| V1 | Layout, header copy, footer disclaimer | As the handoff, with the copy changes in §4.6 |
| V2 | **Pre-call form** (name*, email*, company, phone) | §4.2. Start call disabled until valid |
| V3 | Call states: idle, connecting (Cancel), live (listening / speaking / "One moment"), muted, ended, error | Driven by Vapi events (§4.3) |
| V4 | Ring with 5 bars (teal listening 1.4 s, brand speaking 0.9 s, still at 0.5 opacity while waiting), `prefers-reduced-motion` turns animation off | Handoff spec |
| V5 | Mute / Unmute, End call, elapsed `m:ss` timer | `vapi.setMuted()` |
| V6 | **Live captions**: transcript block, "You" / "RelayPay" rows, partial text shown greyed while speaking, replaced by the final line; auto-scroll; Hide / Show | §4.4 |
| V7 | **Outcome box** when the call ends, from our records | §4.5, `GET /voice/calls/{id}/outcome` |
| V8 | "Did this help?" Yes / No, saved | `POST /voice/calls/{id}/rating` |
| V9 | "Start a new conversation" (form keeps its values) | |
| V10 | Mic denied and connection errors with Try again | Never a raw error |
| V11 | Greeting by name | Page passes `variableValues.name`; the user edits Vapi's first message (§7) |

### Voice page: OUT (and why)

| Feature in the design | Why it's out |
|---|---|
| Text chat mode | Out of scope in the handoff itself |
| "Email me a summary" / "summary sent to…" | No email service |
| Tool-name hints ("Checking transaction TXN-9001") | The browser can't see our backend's tool calls through Vapi. Use "One moment" |
| "Help centre" tile and `support@relaypay.com` | Not in the KB (a dead link and a made-up address). Replace with the dashboard line (§4.6) |

### Console: IN

| # | Feature | Notes |
|---|---|---|
| C1 | Sign in screen (handoff design), one shared login (`CONSOLE_EMAIL` + `CONSOLE_PASSWORD`), signed session cookie, 5 failed tries per 15 min per IP | §5.3 |
| C2 | App shell: sidebar (Dashboard, Cases, Conversations, Customers), header with "Assistant online" | No Analytics or Team items |
| C3 | Dashboard: KPIs (conversations today, answered by the assistant %, open cases, open escalations), "Needs attention" (open escalations first: callback today, then oldest), "Recent conversations" (5) | |
| C4 | Cases: Escalations / Tickets tabs with open counts, chips Open / Resolved, the table (ID, issue + company, priority, status, action), side panel (handover summary, link to the conversation, fields incl. **callback in the caller's local time**, contact method and phone, customer card, related transaction/payout card, simple timeline), **Resolve with a required note** | No owner column |
| C5 | Conversations: list (search, outcome chips), detail (summary, outcome badge, rating, transcript from `conversation_turns`, "What the assistant did" from `tool_calls`, linked ticket/escalation, grounding note per turn) | |
| C6 | Customers: list (company, contact, plan, status, region, open cases, calls) and profile (cases, calls, transactions and payouts, support notes) | |
| C7 | New-item ping: poll every 30 s, soft chime + count badge on Cases, "Enable sound" button, no repeat after refresh (localStorage, wrapped in try/catch) | SPECS §6 |

### Console: OUT (and why)

| Feature in the design | Why it's out |
|---|---|
| Roles (support/admin), Team page, invites, Supabase Auth | No time today; listed as a future improvement in the reflections |
| Owners, assignment, "Take case", due dates, "Overdue" KPI | Needs a team table and SLAs |
| Analytics page and date picker | Time. Only if everything else is done |
| Recording player, "Flag for review" | Not stored today |
| Internal notes on cases (beyond the resolve note) | Keep to the resolve note |

---

## 4. Voice page: how it works

### 4.1 Files

`src/customer_support_agent/web/` (new package): `static/voice/index.html`, `static/voice/voice.js`,
`static/shared/tokens.css`, `static/shared/base.css`, `static/shared/relaypay-logo.png`; console files under
`static/console/`. FastAPI serves them (`StaticFiles`) and the routes in §5.

### 4.2 The form

Inside the card, between the header and the call area. Fields: **Name** (required, 2–80 chars), **Email**
(required, valid email), **Company** (optional), **Phone** (optional; hint "With country code, for callbacks").
Label 13/500, input 44px, 1px `#D5DAE1`, radius 8, focus ring teal. Helper line: "So a specialist can follow up
if needed." Errors as text under the field ("Enter a valid email"). Start call stays disabled until name and email
are valid. When the call starts, the form collapses to one line: "Calling as {name} · {email}" (with an Edit link
only before/after a call). The backend validates and cleans everything again; the browser checks are for the
caller's convenience only.

### 4.3 Vapi wiring

```js
import Vapi from "https://cdn.jsdelivr.net/npm/@vapi-ai/web@2.7.1/+esm";
const { publicKey, assistantId } = await (await fetch("/voice/config")).json();
const vapi = new Vapi(publicKey);
const call = await vapi.start(assistantId, {
  variableValues: { name: firstName },                 // the greeting: "Hi {{name}}, …"
  metadata: { name, email, company, phone },           // read by the backend (api/caller.py)
});
const callId = call?.id;                               // needed for the outcome and rating
```

Events → states: `call-start` → live/listening, start the timer; `speech-start` → speaking; `speech-end` →
listening; `message` with `type === "transcript"` → captions (§4.4); `call-end` → ended, fetch the outcome;
`error` → error state. Mic permission denied (getUserMedia rejected / Vapi error about permissions) → the
"Microphone unavailable" state. Between the caller's final transcript and the next `speech-start`, show
"One moment" (bars still, 0.5 opacity). Vapi's `assistantOverrides.metadata` is what `caller_from_vapi()` reads;
**the first test call through the page is what proves the form data arrives** (check with `relaypay-call`).

### 4.4 Live captions

On `message.type === "transcript"`: `role` (`user` / `assistant`), `transcriptType` (`partial` / `final`),
`transcript`. Keep one "in progress" row per role, shown in ink-3; replace it with the final text when
`final` arrives. Auto-scroll to the bottom unless the user has scrolled up. **Insert text with `textContent`,
never `innerHTML`** (the transcript is the caller's words). Transcript stays visible after the call ends.

### 4.5 Outcome box (after `call-end`)

`GET /voice/calls/{callId}/outcome` (retry a few times over ~5 s: the records are written in the background).
Show, per the handoff's outcome box styles:

| Our record | Title (tone) | Detail |
|---|---|---|
| Escalation, contact by call, window known | "Callback requested" (teal) | "A specialist will call you on Friday 2 October, between 10am and 12pm Lagos time." + "Reference E-1033" |
| Escalation, call any time | "Callback requested" (teal) | "A specialist will call you as soon as one is free." |
| Escalation, email | "Passed to a specialist" (teal) | "A specialist will email you at p•••@gmail.com." |
| Ticket only | "Ticket created" (teal) | "Reference T-1034. Our team will look into it." |
| Neither | "Thanks for calling" (green) | "If anything else comes up, you can reach us through your RelayPay dashboard." |
| Endpoint fails | No box | Just rating + new conversation |

**Never** "booked", "within one business day" or any other timeline (SPECS §6).

### 4.6 Copy changes from the handoff

- Hours: "Specialists are available Monday to Friday, 9am to 7pm Lagos time (WAT)." (Support hours are
  08:00–18:00 UTC; the handoff's "08:00–18:00 WAT" is wrong.)
- Replace "Other ways to get help" tiles with: "You can also contact support through your RelayPay dashboard."
- Error copy: "Allow microphone access in your browser settings and try again." (no email address).
- Rating "No" reply: "Thanks. We will use this to improve."
- Keep: title "Customer support", the intro paragraph, the "You can ask about" chips, the footer disclaimer.

### 4.7 Accessibility and responsiveness

WCAG 2.2 AA contrast; visible focus ring; Start/End call reachable by keyboard; status line `aria-live="polite"`;
captions region `aria-live="polite"` for final lines only; labels tied to inputs; works at 320px wide (16px gutters,
no horizontal scroll); tap targets ≥ 44px.

---

## 5. Backend endpoints to add (thin, read-mostly)

Add as a router in `src/customer_support_agent/api/web.py`, mounted by `create_app`. Use the existing
`Repository` (`db/repository.py`) through `asyncio.to_thread`; catch `RepositoryUnavailable` → 503 with a short
JSON error. All new SQL goes in `Repository` (parameterised, no f-strings with input). Mask emails with
`domain.normalise.mask_email`.

### 5.1 Voice

| Method + path | Returns | Rules |
|---|---|---|
| `GET /` | the voice page | |
| `GET /voice/config` | `{"publicKey", "assistantId"}` from `VAPI_PUBLIC_KEY`, `VAPI_ASSISTANT_ID` | 503 if either is missing. Nothing else, ever |
| `GET /voice/calls/{call_id}/outcome` | `{"outcome": "callback"|"email"|"ticket"|"none", "reference", "callback": "<spoken local window>"|null, "email_masked"}` | Only calls started in the last 2 hours; 404 otherwise. No names, no phone, no full email |
| `POST /voice/calls/{call_id}/rating` `{"helpful": true|false}` | `{"ok": true}` | Same 2-hour window; saved once (later posts ignored) |

The spoken callback window: add a small public helper in `domain/callbacks.py` that formats `(start_utc,
end_utc, timezone)` like `CallbackWindow.spoken` ("Friday 2 October, between 10am and 12pm Lagos time"), reusing
`_clock` and `_city`. Unit-test it.

### 5.2 Console API (all under `/console/api/`, all require the session)

`GET summary` · `GET cases?type=escalation|ticket&status=open|resolved` · `GET cases/{id}` ·
`POST cases/{id}/resolve {"note"}` (note required, 1–500 chars; sets `status='closed'`, `resolved_at`,
`resolution_note`) · `GET conversations?search=&outcome=` (latest 50) · `GET conversations/{id}` (row + turns +
tool_calls + retrieval + events + linked cases) · `GET customers` · `GET customers/{id}` ·
`GET new?since=<iso>` (count + latest ids of tickets/escalations created after `since`).
Conversation outcome for lists/badges: escalation → "Handed to specialist" (amber); ticket only → "Ticket
created" (amber); `abandoned` → "Caller hung up" (grey); any `decline` turn and nothing else → "Could not answer"
(grey); otherwise "Answered by assistant" (green).

### 5.3 Console auth and safety

- `POST /console/login` with email + password checked against `CONSOLE_EMAIL` / `CONSOLE_PASSWORD` using
  `hmac.compare_digest`; on success set an `HttpOnly; Secure (when https); SameSite=Strict` cookie holding a
  signed session (HMAC-SHA256 with `CONSOLE_SESSION_SECRET`, expiry 12 h). `POST /console/logout` clears it.
- 5 failed logins per 15 minutes per client IP → 429 (in memory is fine: one instance).
- Console pages and `/console/api/*` return 401 / redirect to sign-in without a valid cookie.
- State-changing requests (`resolve`) also require the header `X-Requested-With: relaypay-console`.
- Every piece of text from the database is rendered with `textContent` (transcripts, summaries and reasons
  contain caller words and model text). This is the XSS rule from SPECS §8.
- Startup: if `CONSOLE_PASSWORD` or `CONSOLE_SESSION_SECRET` is missing/short (< 16 chars), the console is
  disabled (routes return 503) and a warning is logged; the voice page still works.

---

## 6. Migration `migrations/005_frontend.sql`

```sql
alter table conversations add column if not exists rating text check (rating in ('yes', 'no'));
alter table conversations add column if not exists rated_at timestamptz;
alter table support_tickets add column if not exists resolved_at timestamptz;
alter table support_tickets add column if not exists resolution_note text;
alter table escalations add column if not exists resolved_at timestamptz;
alter table escalations add column if not exists resolution_note text;
```

Apply to both schemas: `DATABASE_SCHEMA=test poetry run relaypay-db` and `DATABASE_SCHEMA=public poetry run
relaypay-db` (the user's `.env` currently points at `test`; a command-line value wins). New `.env.example`
entries: `CONSOLE_EMAIL`, `CONSOLE_SESSION_SECRET` (generate with `python -c "import secrets;
print(secrets.token_urlsafe(32))"`).

---

## 7. Steps for the user (Claude never handles the private key)

1. `.env`: set `VAPI_PUBLIC_KEY`, `VAPI_ASSISTANT_ID`, `CONSOLE_EMAIL`, `CONSOLE_PASSWORD`, `CONSOLE_SESSION_SECRET`.
2. **Greeting by name** (Vapi uses Liquid templates; the default covers dashboard calls with no name). Keep the
   rest of the current first message; only add the name. Example:
   `Hi {{ name | default: "there" }}, thanks for calling RelayPay support. How can I help you today?`
   (If Vapi doesn't render the `default` filter, use plain `{{name}}` and accept "Hi ," on dashboard test calls.)
   Set it in the Vapi dashboard (Assistant → First message), or with a PATCH of `firstMessage` like the other
   HANDOVER commands. It must not contain "goodbye" (the hang-up word).
3. At deploy: restrict the Vapi public key to the site's domain and this assistant (Vapi dashboard).
4. Test locally at `http://127.0.0.1:8000/` (browsers allow the mic on localhost) or the ngrok URL.

---

## 8. Tests (lean, pytest, `tests/api/test_web.py` etc.)

- `/voice/config` returns exactly the two public values; 503 when missing.
- Outcome: callback (spoken local window), email (masked), ticket, none; 404 for an unknown or old call.
- Rating: saved once; bad body 422; old call 404.
- The spoken-window helper (one test, incl. a UTC+1 zone).
- Console: 401 without a session; wrong password; the 6th failed login → 429; resolve needs the header and a
  note; resolve sets the fields; a conversation detail includes turns and tool calls.
- Use `tests/mcp_server/fake_repo.py` style fakes; add any new repository methods to the fake. Real-database
  checks for new SQL go in `tests/db/test_repository_integration.py` (run with `RUN_DB_TESTS=1`).
- Frontend JS: no unit-test framework; check by hand in the browser (states via the console log), and keep
  logic small. Before handing back: open the page at 320px and 1440px wide, tab through it with the keyboard.

---

## 9. Build order and definition of done

1. Static serving + `/voice/config` + the page shell and form (no call yet). Check in the browser.
2. Vapi wiring, states, captions, mute, timer, errors.
3. Outcome + rating endpoints, migration 005, outcome box. **User test call #1 through the page**: confirm with
   `poetry run relaypay-call --schema test` that `form:` shows the typed name/email, the greeting used the name,
   captions followed the call, and the outcome box matched the record.
4. Console auth + shell + Dashboard.
5. Cases (list, side panel, resolve), Conversations, Customers.
6. New-item ping.
7. Update `docs/DESIGN.md` (tokens, the two screens as built), `docs/BUILD_PLAN.md` (tick Phases 6 and 8), SPECS
   where behaviour changed, `.env.example`; then the user's go-ahead to commit on `main` (never push).

Done means: all tests pass (`poetry run pytest -q`), the user's test call through the page shows the form data in
the call record, the console shows that call, its transcript, and its escalation in local time, and nothing on
either page shows a secret, a raw error, a timeline promise, or "booked".
