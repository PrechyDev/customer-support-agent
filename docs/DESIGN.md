# Design

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

The brand gives the colour *names* only. The hex values are **proposals**, to be replaced by the mockup's values. Every text and background pair must meet WCAG AA contrast (4.5:1 for body text).

| Token | Use | Proposed value |
|---|---|---|
| `--color-primary` | Deep blue: main button, logo, headings | `#0F2D52` |
| `--color-accent` | Teal blue: active and listening state, links, focus ring. Used sparingly | `#0E7C86` |
| `--color-bg` | Page background (off-white or light grey) | `#F6F7F9` |
| `--color-surface` | Cards and panels | `#FFFFFF` |
| `--color-text` | Body text | `#1A2233` |
| `--color-text-muted` | Secondary text, timestamps | `#5B6576` |
| `--color-border` | Dividers, card borders | `#E2E6EC` |
| `--color-success` | Completed, closed | `#1E7B4F` |
| `--color-warning` | Delayed, in progress | `#9A6700` |
| `--color-danger` | Errors, failed, escalated | `#B42318` |

Buttons, active states and highlights use colour **with restraint**. There is one primary action per screen.

---

## 3. Typography

- **Font:** Inter (Google Fonts), falling back to the system UI stack: `Inter, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`.
- **No** decorative or monospace fonts. Transaction IDs are shown in the same font.
- **Few weights:** 400 for body, 500 for labels, 600 for headings.
- **Scale:** 14px small or meta, 16px body, 20px section heading, 28px page title.

---

## 4. Voice page (customers)

**Layout:** a single-screen flow. The logo is **centred at the top** (the brand allows top-left or centred; centred suits a single-screen flow). The call control sits in the middle, with a short line of help text below it.

**Content:**
- Title: "RelayPay Support"
- One line: "Talk to our support assistant about payments, payouts, invoices and your account."
- **Call button:** the primary action. "Start call" / "End call".
- **Status line:** says in words what's happening (see states).
- **Live captions (optional):** the last line said by each side, shown as plain text, not bubbles. This helps with noisy rooms and hearing impairments.
- **Privacy note, small:** "Calls are recorded and transcribed to help our support team."
- **Demo notice, small:** "Demo environment: sample account data."

**States (all must be designed):**

| State | What the user sees |
|---|---|
| Idle | "Start call" button, help text |
| Connecting | Button disabled, "Connecting…" |
| Listening | Calm teal indicator, "Listening…" |
| Agent speaking | Indicator changes, "Speaking…" |
| Ended | "Call ended. Thanks for contacting RelayPay." Button returns to "Start call" |
| Mic permission denied | Plain explanation of how to allow the mic, and a retry button |
| Error / connection lost | "We couldn't connect. Please try again." and a retry button. Never a raw error message |

**Behaviour:**
- The logo isn't animated. The listening and speaking indicator is the only motion, and it's subtle. It respects `prefers-reduced-motion`.
- No keys in the page except Vapi's **public** key.

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
