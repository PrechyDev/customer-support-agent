# Support console: backend API contract

Written 01-10-2026. **The backend session owns all Python** (these endpoints, the database, auth). **The frontend
session owns only `src/customer_support_agent/web/static/console/`** and builds the screens from
`../design_handoff_relaypay_v1/` against this contract. Ask the user before changing either side's files.

Decisions (user, 01-10): invites are **copy-link** (no email service); **superadmin** (the user) manages everyone,
**admins** manage support staff only, **support** has no Team page; cases use the design's **ownership flow**;
**basic analytics**.

## Conventions

- Base path `/console/api`. JSON in, JSON out. Times are ISO 8601 UTC (`2026-10-01T17:18:59Z`); the browser
  formats them. Errors: `{"error": "<code>", "detail": "<plain sentence safe to show>"}` with status
  400 (validation), 401 (not signed in), 403 (role not allowed), 404, 409 (conflict), 410 (invite expired/used),
  429 (too many tries), 503 (database down or console not configured).
  Case actions (take, resolve, reopen) return `409 case_changed` when someone else changed the case first:
  show the detail and reload the case.
- **Every POST/PATCH must send the header `X-Requested-With: relaypay-console`** (CSRF guard), plus
  `Content-Type: application/json`.
- Session: an HttpOnly cookie set by login/accept (`SameSite=Strict`, 12 h). The browser never sees a token.
  On any 401, show the sign-in screen.
- Render every string from the API with `textContent` (transcripts and summaries contain caller words).
- Pages: `GET /console` and `GET /console/<anything>` (e.g. `/console/invite/<token>`) serve
  `web/static/console/index.html` (single-page app). Static files: `/static/console/...`.

## Roles

| Can… | support | admin | superadmin |
|---|---|---|---|
| Dashboard, Conversations, Customers, Analytics | ✓ | ✓ | ✓ |
| Take an unassigned case; resolve own cases; add notes | ✓ | ✓ | ✓ |
| Assign a case to anyone; resolve any case; reopen | — | ✓ | ✓ |
| Team page; invite / resend / reset / disable **support** | — | ✓ | ✓ |
| Invite / change role / disable **admins** | — | — | ✓ |
| Change or disable the superadmin | nobody | | |

`me.permissions` (below) tells the UI what to show; the backend enforces it anyway.

## Auth and invites

| Method + path | Body | Returns |
|---|---|---|
| `POST /login` | `{email, password}` | `200 {member}` + cookie. Wrong details: `401 invalid_credentials` ("Email or password is incorrect."). Pending or disabled: same 401 (no hint). 5 failed tries per 15 min per address and email: `429 too_many_attempts` |
| `POST /logout` | — | `200 {ok: true}`, cookie cleared |
| `GET /me` | — | `{member, permissions: {manage_team, manage_admins, assign_cases, reopen_cases}}` or 401 |
| `GET /invites/{token}` | — | `{email, role, kind: "invite"|"reset"}`; `410 invite_invalid` if expired, used or unknown |
| `POST /invites/{token}/accept` | `{name, password, confirm_password}` | `200 {member}` + cookie (signed in). Rules: name 2–80 chars; password 8–128 chars, not the email; confirm must match. Errors `400 {"error":"invalid_input","fields":{"password":"…"}}` |

`member` = `{member_id, email, name, role, status, created_at, activated_at, last_login_at, invited_by_name}`.
Status: `pending` (invite sent) · `active` · `disabled`.

**Forgot password** (sign-in screen link): show "Ask an admin to send you a reset link." An admin uses *Reset
link* on the Team page; the person opens it and sets a new password (same accept screen, `kind: "reset"`).

## Team (admin, superadmin)

| Method + path | Body | Returns |
|---|---|---|
| `GET /team` | — | `{members: [member…]}` (superadmin first, then by name) |
| `POST /team/invites` | `{email, role: "admin"|"support"}` | `201 {member, invite_url, expires_at}`. `409 already_member` if the email exists |
| `POST /team/{member_id}/resend` | — | `{invite_url, expires_at}` (pending only; old link stops working) |
| `POST /team/{member_id}/reset-link` | — | `{invite_url, expires_at}` (active only) |
| `PATCH /team/{member_id}` | `{role?: "admin"|"support", status?: "active"|"disabled"}` | `{member}`. Disabling signs them out everywhere |

`invite_url` is absolute (`https://…/console/invite/<token>`), valid 72 h, single use. Show it with a Copy button:
it is shown once, never stored in plain text.

## Dashboard

`GET /summary` →
```json
{"kpis": {"conversations_today": 4, "live_now": 1, "answered_by_assistant_pct": 62,
          "open_cases": 7, "assigned_to_me": 2, "unassigned": 3},
 "needs_attention": [case_row…],   // max 5: callback today, then unassigned, then oldest open
 "recent_conversations": [conversation_row…]}   // 5
```
Support: `needs_attention` holds only their own and unassigned cases.

## Pagination (added 01-10-2026; built and tested)

`GET /conversations`, `GET /cases` and `GET /customers` take `page` (1-based, default 1) and `page_size`
(default 25, max 100). The database returns only that page (LIMIT/OFFSET).

- Each reply keeps its current keys and adds `"pagination": {"page": 2, "page_size": 25, "total": 132}`;
  `total` = rows matching the current filter and search. `counts` (the chip numbers) are unchanged.
- Order is stable so pages don't shift: conversations and cases newest first, then by ID; customers by company
  name, then ID.
- A page past the end returns an empty list with the real `total` (not a 404). A bad `page` or `page_size` →
  `400 invalid_input`.
- `case_row` gains `ticket_id` (an escalation's linked ticket; for a ticket, its own ID), so the case panel can
  show the pair.
- `GET /conversations` no longer takes `limit` (`page_size` replaces it).
- The console shows a pager under each of the three lists ("Showing 26–50 of 132", Previous / Next); the page is
  in the URL, and changing a search or filter goes back to page 1. Without `pagination` in a reply it shows no
  pager, so it works before and after this change.

## Cases

`case_row` = `{case_id, case_type: "escalation"|"ticket", title, category, priority, status, owner: {member_id,
name}|null, customer_id, company, reference, callback: {spoken, start_utc}|null, contact_method, created_at,
resolved_at, conversation_id}`. Status: `open` · `in progress` · `closed`.
An escalation always links a ticket, and the two are **one case**: it's listed once (as the escalation), and
take, assign, resolve and reopen on the escalation apply to its ticket too. A ticket with no escalation is a
case of its own. There are no separate Escalations / Tickets tabs: one Cases list, labelled per row.

| Method + path | Body | Returns |
|---|---|---|
| `GET /cases?filter=open|mine|unassigned|resolved&page=&page_size=` (optional `type=escalation|ticket`) | — | `{cases: [case_row…], counts: {open, mine, unassigned, resolved}}`. **Without `type`: one list of every case, newest first** (an escalation and its ticket are one case, listed once as the escalation). Use `case_type` and `contact_method` on each row for its label |
| `GET /cases/{type}/{case_id}` | — | `{case: case_row + {reason, summary, contact: {name, email (full, staff only), phone}, verified, preferred_time}, customer: {…}|null, related: {kind, reference, status, line}|null, conversation: {conversation_id, summary, started_at, duration_s}|null, timeline: [{when, who, kind, text}]}` |
| `POST /cases/{type}/{case_id}/take` | — | `{case}` (unassigned only → owner = you, status in progress) |
| `POST /cases/{type}/{case_id}/assign` | `{member_id}` | `{case}` (admin+) |
| `POST /cases/{type}/{case_id}/resolve` | `{note}` (1–500 chars) | `{case}` (own, or admin+) |
| `POST /cases/{type}/{case_id}/reopen` | — | `{case}` (admin+) |
| `POST /cases/{type}/{case_id}/notes` | `{text}` (1–1000 chars) | `{timeline_entry}` |

## Conversations

`conversation_row` = `{conversation_id, caller, started_at, duration_s, outcome, summary, rating, channel}`.
`outcome`: `answered` (green) · `handed_to_specialist` (amber) · `ticket_created` (amber) · `could_not_answer`
(grey) · `caller_hung_up` (grey). `caller` = verified company, else the form name, else "Unknown caller".

| Method + path | Returns |
|---|---|
| `GET /conversations?search=&outcome=&page=&page_size=` | `{conversations: [conversation_row…], counts: {all, answered, …}}` |
| `GET /conversations/{id}` | `{conversation: row + {verified_customer_id, form: {name, email}}, transcript: [{when, speaker: "caller"|"assistant", text, answer_type, note}], actions: [{when, label, detail, ok}], cases: [case_row…], searches: [{query, chunks}]}` |

`actions` are plain-language steps from tool calls ("Checked transaction TXN-9001", "Opened ticket T-1057",
"Handed to a specialist E-1056", "Used help article …").

## Customers

| Method + path | Returns |
|---|---|
| `GET /customers?search=&page=&page_size=` | `{customers: [{customer_id, company, contact_name, contact_email, plan, account_status, region, open_cases, calls}]}` |
| `GET /customers/{id}` | `{customer: {…, kyc_status, support_notes}, cases: [case_row…], conversations: [conversation_row…], transactions: [{transaction_id, type, amount, currency, status, created_at}], payouts: [{payout_id, transaction_id, amount, currency, status, scheduled_for}]}` |

## Analytics

`GET /analytics?from=YYYY-MM-DD&to=YYYY-MM-DD` (inclusive, max 366 days; default last 7 days) →
```json
{"range": {"from": "…", "to": "…"},
 "kpis": {"conversations": 12, "conversations_change_pct": 20, "answered_by_assistant_pct": 58,
          "handed_to_specialist_pct": 33, "rated_helpful_pct": 80, "average_duration_s": 142},
 "series": {"bucket": "day"|"week"|"month", "points": [{"start": "2026-09-25", "count": 3}]},
 "ended": {"answered": 7, "handed_to_specialist": 4, "ticket_created": 0, "could_not_answer": 1, "caller_hung_up": 0},
 "unanswered": [{"question": "Do you have a mobile app?", "times": 2}]}
```

## New-item ping

`GET /new?since=<iso>` → `{count, latest: [case_row…], now: "<iso>"}` (cases created after `since`). Poll every
30 s; store `now` for the next call.
