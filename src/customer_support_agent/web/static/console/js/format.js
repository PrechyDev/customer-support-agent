// Labels, badge colours and formatting. Times arrive as ISO UTC and are shown in the viewer's local time.
// Badge mapping follows the handoff README "Status badges".

const time = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" });
const day = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });
const dayYear = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" });

export const OUTCOMES = {
  answered: ["Answered by assistant", "green"],
  handed_to_specialist: ["Handed to specialist", "amber"],
  ticket_created: ["Logged for the team", "amber"], // a ticket with no escalation
  could_not_answer: ["Could not answer", "grey"],
  caller_hung_up: ["Caller hung up", "grey"],
};
export const outcomeLabel = (key) => OUTCOMES[key]?.[0] || "Unknown";
const LIVE_WINDOW_MS = 2 * 60 * 60 * 1000;
// A call that hasn't ended (and started recently) is live: its outcome isn't known yet.
export function conversationBadge(row) {
  const live = (row.duration_s === null || row.duration_s === undefined)
    && Date.now() - new Date(row.started_at).getTime() < LIVE_WINDOW_MS;
  return live ? ["Live now", "teal"] : [outcomeLabel(row.outcome), outcomeTone(row.outcome)];
}
export const outcomeTone = (key) => OUTCOMES[key]?.[1] || "grey";

const STATUS = { open: ["Open", "blue"], "in progress": ["In progress", "teal"], closed: ["Resolved", "green"] };
export const caseStatus = (status) => STATUS[status] || [status, "grey"];
const PRIORITY = { high: "amber", medium: "blue", low: "grey" };
export const priorityTone = (priority) => PRIORITY[priority] || "grey";
export const capitalise = (text) => (text ? text.charAt(0).toUpperCase() + text.slice(1) : "");

const MONEY_TONES = {
  completed: "green", active: "green", approved: "green", processing: "teal", scheduled: "blue",
  delayed: "amber", "review required": "amber", restricted: "amber", "pending verification": "blue", pending: "blue",
  failed: "red",
};
export const statusTone = (status) => MONEY_TONES[String(status || "").toLowerCase()] || "grey";

export const ROLES = { superadmin: "Owner", admin: "Admin", support: "Support staff" };

function sameDay(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

// "14:05" today, "Yesterday 14:05", "Sep 29, 14:05"
export function when(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (sameDay(date, now)) return time.format(date);
  if (sameDay(date, yesterday)) return `Yesterday ${time.format(date)}`;
  return `${(date.getFullYear() === now.getFullYear() ? day : dayYear).format(date)}, ${time.format(date)}`;
}

export const clockTime = (iso) => (iso ? time.format(new Date(iso)) : "");
export const shortDate = (iso) => (iso ? dayYear.format(new Date(`${iso.slice(0, 10)}T12:00:00`)) : "");

export function duration(seconds) {
  if (seconds === null || seconds === undefined) return "In progress";
  const s = Math.max(0, Math.round(seconds));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

export function money(amount, currency) {
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(amount);
  } catch {
    return `${amount} ${currency || ""}`.trim();
  }
}

// The backend's check of each reply (agent/grounding.py, confidence_note) -> what a reviewer needs to see.
// "flag": something to look at; "quiet": where the facts came from; "routine": nothing to check (hidden by default).
export function noteView(note) {
  if (!note) return null;
  const flags = [];
  const notGrounded = note.match(/NOT GROUNDED: ([^.]*)/);
  if (notGrounded) flags.push(`Not grounded: ${notGrounded[1]}`);
  const phrase = note.match(/PHRASE FLAG: ([^.]*)/);
  if (phrase) flags.push(`Phrase flag: ${phrase[1]}`);
  const fixed = note.match(/(?:Fixed backend line|Followed by a fixed line) \(([^)]*)\)/);
  if (fixed && fixed[1] !== "ok") flags.push(`Fallback line used (${fixed[1]})`);
  if (flags.length) return { kind: "flag", text: flags.join(" · "), raw: note };
  const sources = note.match(/Grounded in: ([^.]*)\./);
  if (sources) return { kind: "quiet", text: `Sources: ${sources[1]}`, raw: note };
  const tool = note.match(/From (?:an earlier )?tool result(?: in this call)?: ([^.]*)\./);
  if (tool) return { kind: "quiet", text: `Checked: ${tool[1]}`, raw: note };
  if (note.startsWith("Declined")) return { kind: "quiet", text: note.split(" (labelled")[0].replace(/\.$/, ""), raw: note };
  return { kind: "routine", text: note, raw: note };
}

export function ratingLabel(rating) {
  return rating === "yes" ? "Rated helpful" : rating === "no" ? "Rated not helpful" : "Not rated";
}

export function pct(value) {
  return value === null || value === undefined ? "–" : `${value}%`;
}

// How a case will be followed up (docs/FRONTEND_NOTE_CASES.md): an escalation is a person to contact (by call or
// email), a ticket on its own is logged for the team to fix. The callback window is already in the caller's time.
export function caseFollowUp(row) {
  if (row.case_type === "escalation" && row.callback?.spoken) {
    const today = sameDay(new Date(row.callback.start_utc), new Date());
    return { label: "Callback", detail: row.callback.spoken, text: `Callback ${row.callback.spoken}`, today };
  }
  if (row.case_type === "escalation" && row.contact_method === "call") { // the caller said "any time"
    return { label: "Callback", detail: "any time", text: "Callback: any time", today: false };
  }
  if (row.case_type === "escalation") return { label: "Follow up by email", detail: "", text: "Follow up by email", today: false };
  return { label: "Logged", detail: "", text: "Logged", today: false };
}
