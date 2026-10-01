# Note for the frontend session: one Cases list (01-10-2026)

The backend changed so that an escalation and its ticket are always **one case**. Please make the console match.
Backend only, already done and tested: you don't need to touch any Python.

## What changed in the API (see `docs/CONSOLE_API.md`, Cases)

- `GET /console/api/cases?filter=open|mine|unassigned|resolved` **without `type`** now returns every case in
  one list, newest first. A ticket that belongs to an escalation is not in the list on its own (it's part of
  the escalation's case). `counts` covers the whole list.
- Take, assign, resolve and reopen on an escalation now also update its linked ticket. Nothing to do on your
  side; just keep calling the same endpoints with the row's `case_type` and `case_id`.
- `type=escalation` / `type=ticket` still work, but the console shouldn't use them any more.

## What to change in the console

1. **Remove the Escalations / Tickets tabs** on the Cases page. Keep the filter row
   (Open · Mine · Unassigned · Resolved) and call `/cases` without `type`.
2. **Label each row** from the fields it already has:
   - `case_type == "escalation"` and `callback` set → "Callback" + `callback.spoken` (e.g. "Callback Fri 2 Oct, 10am–12pm Lagos time")
   - `case_type == "escalation"` otherwise → "Follow up by email"
   - `case_type == "ticket"` → "Logged" (the team fixes it; no customer contact needed)
3. **Actions and the detail page** stay as they are: use the row's own `case_type` and `case_id` in
   `/cases/{case_type}/{case_id}/…`.
4. The dashboard's case numbers already count both kinds together, so they now match the list.

## Why

Staff think in problems, not database tables. The Tickets tab was nearly always empty (most calls that need a
person become escalations), which was confusing. Real helpdesks (Zendesk, Freshdesk) show one queue where
"escalated" is a state of the case, not a second list.
