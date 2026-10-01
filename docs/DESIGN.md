# Design

> **01-10-2026: the handoff is the source of truth: `../../design_handoff_relaypay_v1/README.md`** (Claude Design handoff, high fidelity) and the scope in `docs/FRONTEND_PLAN.md`. §2 and §4 below now match what was built.

The visual and interaction design for the two screens: the **voice page** (for customers) and the **support console** (for RelayPay staff).

Based on `../../aat-c3-week-6-support-agent-main/assets/brand-direction.md` and the PRD. **Mockups from Claude Design will be added below** (§6). Where a mockup and this doc disagree, update this doc to match the mockup.

Last updated: 29-09-2026

---

## 1. Principles

RelayPay handles money, compliance and trust-sensitive work. The interface should feel **professional, calm, minimal and trustworthy**.

- Nothing playful, flashy or experimental.
- **No** bright or neon colours, gradients, emojis, over-branding or experimental layouts.
- **No chat-heavy visual treatment.** The voice page is a call, not a messenger. No bubbles, avatars or typing dots.
- When unsure, make it simpler and more neutral.

---

## 2. Colour tokens

From the design handoff (01-10-2026), in `src/customer_support_agent/web/static/shared/tokens.css`: the **only** place colours are
defined; everything else uses `var(--…)`. No shadows, no gradients.

| Token | Use | Value |
|---|---|---|
| `--ink` / `--ink-2` / `--ink-3` / `--ink-4` | Text: primary / secondary / meta / placeholder | `#0F1B2D` / `#5A6475` / `#6B7483` / `#8A93A1` |
| `--brand` (hover `--brand-hover`) | Primary buttons, links, active nav, "RelayPay" caption label | `#0E3476` (`#0A2860`) |
| `--teal` | Listening state, focus outline, link hover | `#1683AC` |
| `--page` / `--surface` / `--subtle` | Background / cards / insets | `#F5F6F8` / `#FFFFFF` / `#FAFBFC` |
| `--border` / `--border-input` / `--divider` | Card borders / inputs and secondary buttons / section lines | `#E3E6EB` / `#D5DAE1` / `#EDEFF2` |
| `--danger` (hover `--danger-hover`) | End call, error ring | `#B42318` (`#912018`) |
| Badges `--{green,blue,teal,amber,red,grey}-{bg,fg}` | Status badges (console) | handoff README "Status badges" |

Focus: a 2px teal outline. Buttons, active states and highlights use colour **with restraint**: one primary action per screen.

---

## 3. Typography

- **Font:** Inter (Google Fonts), falling back to the system UI stack: `Inter, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`.
- **No** decorative or monospace fonts. Transaction IDs are shown in the same font.
- **Few weights:** 400 for body, 500 for labels, 600 for headings.
- **Scale:** 14px small or meta, 16px body, 20px section heading, 28px page title.

---

## 4. Voice page (customers): as built (01-10-2026)

Served at `/` by FastAPI. Plain HTML, CSS and JS modules, no build step (`web/static/voice/`). Layout, copy and states
follow the handoff's "Screen 1", with the copy changes in FRONTEND_PLAN §4.6.

- **Two screens** (changed 01-10 after the user's first look):
  1. **Details:** header, the form in one column (Name and Email required, Company and Phone optional; phone needs a
     country code), a full-width Start call button, then "You can ask about" and the help lines. Errors show only after
     a field was typed in and left, or after pressing Start call (which then jumps to the first wrong field).
  2. **Call:** "Calling as {name} · {email}" (Edit after the call), the ring, status and buttons, then the outcome and
     transcript. "Start a new conversation" goes back to the details screen with the values kept.
- **Connecting:** "Calling RelayPay", and a soft ringing tone (400 + 450 Hz double ring, Web Audio, no file) from the
  moment the mic is allowed until Vapi connects; it also stops on Cancel, an error or after 30 s.
- **Call states:** connecting (Cancel), live (Listening / RelayPay is speaking / One moment / You are muted,
  `m:ss` timer), ended, error (Microphone unavailable, or Call could not connect, with Try again and Back). Never a raw error.
- **Ring:** 5 bars; teal 1.4 s while listening, brand 0.9 s while speaking, still at 0.5 opacity for "One moment".
  `prefers-reduced-motion` stops all animation.
- **Live captions:** "You" / "RelayPay" rows, no bubbles; text in progress in ink-3, replaced by the final line;
  auto-scroll unless scrolled up; Hide/Show; kept after the call. Inserted with `textContent` only.
- **After the call:** an outcome box from our own records (Callback requested / Passed to a specialist / Ticket created /
  Thanks for calling; never "booked" or a timeline), "Did this help?" Yes/No (saved once), "Start a new conversation"
  (the form keeps its values).
- **Out:** text chat, email summary, tool-name hints, the help-centre tile and support email (FRONTEND_PLAN §3).
- No keys in the page except Vapi's **public** key, fetched from `/voice/config`.

---

## 5. Support console (RelayPay staff): as built (01-10-2026)

Served at `/console` (single page; `web/static/console/`). Plain HTML, CSS and JS modules, no build step. Layout
follows the handoff's "Screen 2"; the API and the role rules are in `docs/CONSOLE_API.md` (the backend owns them).

- **Access:** sign-in (email + password, HttpOnly cookie); accounts come from copy-link invites
  (`/console/invite/<token>`, also used for password resets). "Forgot password?" says to ask an admin.
  Roles: owner (superadmin), admin, support. The screens show only what a role may do; the backend checks again.
- **Shell:** sidebar (Dashboard, Cases with the open count, Conversations, Customers, Analytics; Team for admins),
  top bar with the page title, "Enable sound" and "Assistant online · N live". Below 900 px the sidebar becomes a
  menu.
- **Dashboard:** five KPIs, "Needs attention" (callback today, then unassigned, then oldest; support see only
  their own and unassigned), five recent conversations.
- **Cases:** one list of every case (an escalation and its ticket are one case; changed 01-10, see
  `docs/FRONTEND_NOTE_CASES.md`), with Open / Mine / Unassigned / Resolved chips. Each row shows priority and how
  it will be followed up: "Callback" + the window in the caller's local time, "Follow up by email", or "Logged"
  (a ticket on its own: the team fixes it, no customer contact). Then owner, status, and Take / Resolve / Reopen.
  A row opens the side panel (560 px, expandable; its own URL): handover summary with a link to the conversation,
  activity timeline, internal notes, fields (callback, contact details, reference, the escalation's linked
  ticket), customer card, related payment or payout. Resolve needs a note (dialog). Admins pick an owner.
- **Conversations:** list with search and outcome chips; detail with summary, links to its cases and customer,
  "What the assistant did" (tool calls and help-article searches), and the transcript. Under each reply, the
  backend's check: "Not grounded" and "Phrase flag" stand out (amber), "Sources: …" is quiet, and routine notes
  ("no facts stated") appear only with "Show all checks". A call still in progress shows "Live now".
- **Customers:** list with search; profile with open cases, payments and payouts, conversations, account fields
  and support notes.
- **Analytics:** date range (presets + calendar, applied on Apply), KPIs, conversations per day/week/month, how
  conversations ended (each call counted once, by its biggest outcome; a ticket with no escalation is "Logged for
  the team"), questions the assistant couldn't answer.
- **Paging:** Conversations, Cases and Customers show 25 at a time ("Showing 26–50 of 132", Previous / Next); the
  page is in the URL, and a new search or filter goes back to page 1.
- **Team:** invite (the link is shown once with a Copy button), resend, reset link, change role (owner only),
  disable / enable.
- **New-item ping:** for new escalations and tickets (not conversations). Checks every 30 s; an "N new" badge on
  Cases, and a soft two-note chime with sound on. The sound button toggles: "Enable sound" → "Sound on" → "Sound
  off"; the choice and the last check time are remembered, so a refresh doesn't ping again.
- **Out (as decided):** recordings, "Flag for review", "Log callback", top topics, due dates and SLAs.
- **Status badges:** a text label plus a muted colour (handoff mapping). Never colour alone. All API text is
  inserted as text, never HTML.

---

## 6. Mockups

> To be added: Claude Design mockups for the voice page and the support console. Paste the images or links here, and update the tokens in §2 to match.

- Voice page: _pending_
- Support console: _pending_

---

## 7. Accessibility and responsiveness

- WCAG 2.2 AA: text contrast, a visible focus ring (accent colour), and full keyboard use (the call button reachable and usable with Enter/Space).
- Status changes are announced to screen readers (`aria-live="polite"` on the status line).
- Works at phone width (a 16px side gutter, no horizontal scroll). Tables in the console scroll inside their card on small screens.
- Tap targets of at least 44×44px.
