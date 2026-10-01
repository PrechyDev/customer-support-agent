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

## 5. Support console (RelayPay staff)

**Access:** behind a login (at least one shared login). It is never public, because it shows customer contact details.

**Layout:** the logo at the **top-left**, a simple top bar, and content in cards and tables. No sidebar needed for the first version.

**Sections (first version):**
1. **Summary row:**
   - total conversations
   - escalated (count)
   - open tickets
   - open escalations
2. **Recent conversations:** a table with time, customer (or "unverified"), channel, final status (answered, clarified, escalated, declined, abandoned) and a one-line summary. A row opens the conversation detail.
3. **Conversation detail:**
   - the turn-by-turn transcript
   - tools used
   - KB chunks used
   - any linked ticket or escalation
4. **Escalations:** reason, category, name, email, preferred callback time, call-booked flag, verified yes/no, status. This is what staff use to reach out to the customer.
5. **Customers:** a list of seed customers and the calls we've had with each one.

**New-item notification:**
- A short, soft chime (not an alarm) plus a count badge on "Escalations" / "Tickets" when a new item arrives.
- An **"Enable sound"** button in the top bar, because browsers block audio until the page is clicked. Once it's on, it shows "Sound on".
- The badge clears when staff open the list.
- Never sound alone: the badge makes it visible for anyone with sound off.

**Not in the first version** (see Future improvements in the reflections notes): staff roles, assigning escalations or tickets, KB editing and approval.

**Status badges:** a text label plus a muted colour from §2. Never colour alone.

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
