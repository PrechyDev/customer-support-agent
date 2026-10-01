// Dashboard: KPIs, "Needs attention" (callback today, then unassigned, then oldest) and recent conversations.

import { api } from "../api.js";
import { badge, emptyRow, h } from "../dom.js";
import { caseFollowUp, pct, priorityTone, when, conversationBadge } from "../format.js";

function kpi(label, value, note, tone) {
  return h("div", { class: "kpi" }, h("span", { class: "label" }, label),
    h("span", { class: `value ${tone || ""}` }, value), h("span", { class: "note" }, note || " "));
}

export function reasonFor(row) {
  const due = caseFollowUp(row);
  if (due.today) return ["Callback today", "amber"];
  if (!row.owner) return ["Unassigned", "amber"];
  return [row.priority === "high" ? "High priority" : "Open", priorityTone(row.priority)];
}

export function caseLink(row) {
  return `/console/cases/${row.case_type}/${encodeURIComponent(row.case_id)}`;
}

export async function render(container, params, ctx) {
  const data = await api("/summary");
  const k = data.kpis;
  const admin = ctx.permissions.assign_cases;
  const needs = data.needs_attention.map((row) => {
    const [reason, tone] = reasonFor(row);
    return h("a", { class: "list-row", href: caseLink(row) },
      h("span", { class: "stack" }, h("span", { class: "title ellipsis" }, row.title),
        h("span", { class: "meta" }, [row.case_id, row.company || "No customer on file", caseFollowUp(row).text].join(" · "))),
      badge(reason, tone));
  });
  const recent = data.recent_conversations.map((row) => h("a", { class: "list-row", href: `/console/conversations/${encodeURIComponent(row.conversation_id)}` },
    h("span", { class: "stack" },
      h("span", { class: "title" }, row.caller, h("span", { class: "muted", style: "font-weight:400" }, ` · ${when(row.started_at)}`)),
      h("span", { class: "line ellipsis" }, row.summary || "No summary yet.")),
    badge(...conversationBadge(row))));

  container.replaceChildren(h("div", { class: "page" },
    h("div", { class: "kpis" },
      kpi("Conversations today", String(k.conversations_today), k.live_now ? `${k.live_now} live now` : ""),
      kpi("Answered by assistant", pct(k.answered_by_assistant_pct), "of today's conversations"),
      admin ? kpi("Open cases", String(k.open_cases), "escalations and tickets")
        : kpi("Assigned to you", String(k.assigned_to_me), "open cases"),
      kpi("Unassigned", String(k.unassigned), "waiting for an owner", k.unassigned ? "amber" : ""),
      admin ? kpi("Assigned to you", String(k.assigned_to_me), "open cases") : kpi("Open cases", String(k.open_cases), "across the team")),
    h("div", { class: "dash-grid" },
      h("section", { class: "card", "aria-labelledby": "needs-title" },
        h("div", { class: "card-head" }, h("span", { class: "card-title", id: "needs-title" }, "Needs attention"),
          h("a", { href: "/console/cases", class: "link-button" }, "View all cases")),
        needs.length ? needs : emptyRow("Nothing needs attention right now.")),
      h("section", { class: "card", "aria-labelledby": "recent-title" },
        h("div", { class: "card-head" }, h("span", { class: "card-title", id: "recent-title" }, "Recent conversations"),
          h("a", { href: "/console/conversations", class: "link-button" }, "View all")),
        recent.length ? recent : emptyRow("No conversations yet.")))));
  return null;
}
