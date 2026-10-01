// The case side panel (handoff "Case side panel"): 560 px, expandable to the full content width.

import { api, post } from "../api.js";
import { append, badge, clear, h, icon, initials, toast } from "../dom.js";
import { caseStatus, capitalise, duration, priorityTone, statusTone, when } from "../format.js";
import { caseActions, ownerControl, runAction } from "./cases.js";

const NOTE_MAX = 1000;

function fieldRows(rows) {
  return h("section", { class: "card fields" }, rows.filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(([label, value]) => h("div", { class: "field-row" }, h("span", {}, label), h("span", {}, value))));
}

function contactLine(contact) {
  return [contact?.name, contact?.email].filter(Boolean).join(" · ");
}

export async function openCasePanel(type, id, ctx, { onChanged, onClose }) {
  const before = document.activeElement;
  let wide = false;
  let closed = false;
  const what = h("span", { class: "what" }, `${type === "escalation" ? "Escalation" : "Ticket"} · ${id}`);
  const widen = h("button", { type: "button", class: "icon-button panel-widen", "aria-label": "Expand panel", title: "Expand panel" }, icon("expand"));
  const closeButton = h("button", { type: "button", class: "icon-button", "aria-label": "Close panel" }, icon("close"));
  const inner = h("div", { class: "panel-inner" }, h("p", { class: "muted" }, "Loading…"));
  const panel = h("aside", { class: "panel", role: "dialog", "aria-modal": "true", "aria-label": `Case ${id}`, tabindex: "-1" },
    h("div", { class: "panel-head" }, what, h("div", { style: "display:flex;gap:2px" }, widen, closeButton)),
    h("div", { class: "panel-body" }, inner));
  const backdrop = h("div", { class: "backdrop" });

  function close({ silent = false } = {}) {
    if (closed) return;
    closed = true;
    document.removeEventListener("keydown", onKey);
    panel.remove();
    backdrop.remove();
    if (!silent) {
      onClose();
      // the row that opened it may have been redrawn: fall back to the main content
      (before?.isConnected ? before : document.getElementById("content"))?.focus?.({ preventScroll: true });
    }
  }

  function onKey(event) {
    if (document.querySelector(".modal")) return; // the Resolve dialog handles its own keys
    if (event.key === "Escape") close();
    if (event.key === "Tab") { // keep focus inside the panel while it's open
      const items = [...panel.querySelectorAll("a[href], button:not([disabled]), select, textarea, input")]
        .filter((el) => el.offsetParent !== null);
      if (!items.length) return;
      const first = items[0], last = items[items.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === panel)) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      else if (!panel.contains(document.activeElement)) { event.preventDefault(); first.focus(); }
    }
  }

  widen.addEventListener("click", () => {
    wide = !wide;
    panel.classList.toggle("wide", wide);
    widen.replaceChildren(icon(wide ? "collapse" : "expand"));
    widen.setAttribute("aria-label", wide ? "Collapse panel" : "Expand panel");
    widen.title = widen.getAttribute("aria-label");
  });
  closeButton.addEventListener("click", () => close());
  backdrop.addEventListener("click", () => close());
  document.addEventListener("keydown", onKey);
  document.body.append(backdrop, panel);
  panel.focus();

  async function reload() {
    if (closed) return;
    let data;
    try {
      data = await api(`/cases/${type}/${encodeURIComponent(id)}`);
    } catch (error) {
      clear(inner).append(h("div", { class: "notice", role: "alert" }, error.message));
      return;
    }
    if (!closed) draw(data);
  }

  const changed = async () => {
    onChanged();
    await reload();
  };

  async function draw({ case: row, customer, related, conversation, timeline }) {
    const can = caseActions(row, ctx);
    const [statusText, statusTone_] = caseStatus(row.status);
    const act = (kind, extra) => () => runAction(row, kind, ctx, changed, extra);
    const owner = can.assign
      ? h("label", {}, "Owner", await ownerControl(row, ctx, (memberId) => runAction(row, "assign", ctx, changed, memberId)))
      : null;

    const note = h("textarea", { class: "textarea", rows: 3, maxlength: NOTE_MAX, placeholder: "Add an internal note",
      "aria-label": "Internal note", "aria-describedby": "note-help" });
    const addNote = h("button", { type: "button", class: "btn btn-secondary btn-sm", disabled: true }, "Add note");
    note.addEventListener("input", () => { addNote.disabled = !note.value.trim(); });
    addNote.addEventListener("click", async () => {
      addNote.disabled = true;
      try {
        await post(`/cases/${type}/${encodeURIComponent(id)}/notes`, { text: note.value.trim() });
        toast("Note added.");
        await reload();
      } catch (error) {
        toast(error.message);
        addNote.disabled = !note.value.trim();
      }
    });

    const callback = row.callback?.spoken ? row.callback.spoken
      : row.contact_method === "call" ? "Any time (next free specialist)" : null;
    const contactMethod = row.contact_method ? (row.contact_method === "call" ? "Phone call" : "Email") : null;
    const contact = row.contact || {};

    const handover = conversation ? h("section", { class: "card card-pad" },
      h("div", { style: "display:flex;justify-content:space-between;align-items:center;gap:8px" },
        h("span", { class: "card-label" }, "Handed over by the assistant"),
        h("a", { class: "link-button", href: `/console/conversations/${encodeURIComponent(conversation.conversation_id)}` }, "Open conversation")),
      h("div", { class: "text" }, conversation.summary || row.summary || row.reason || "No summary was recorded for this call."),
      h("div", { class: "small muted" }, ["Voice", when(conversation.started_at), duration(conversation.duration_s)].join(" · "))) : null;

    const activity = h("section", { class: "card" },
      h("div", { class: "card-head" }, h("span", { class: "card-title" }, "Activity")),
      h("div", { class: "timeline" }, timeline.map((entry) => {
        const assistant = entry.who === "Assistant" || entry.who === "System";
        return h("div", { class: "tl-item" },
          h("div", { class: `avatar small ${assistant ? "ai" : ""}`, "aria-hidden": "true" }, assistant ? "AI" : initials(entry.who)),
          h("div", { style: "display:flex;flex-direction:column;gap:3px;min-width:0" },
            h("div", { class: "who" }, h("span", { class: "strong" }, entry.who), h("span", { class: "muted" }, ` · ${when(entry.when)}`)),
            h("div", { class: "text" }, entry.text)));
      })),
      h("div", { class: "note-form" }, note,
        h("div", { class: "row" }, h("span", { class: "small muted", id: "note-help" }, "Internal only. Never shared with the customer."), addNote)));

    const customerCard = customer ? h("section", { class: "card card-pad" },
      h("div", { style: "display:flex;justify-content:space-between;align-items:center" },
        h("span", { class: "card-label" }, "Customer"),
        h("a", { class: "link-button", href: `/console/customers/${encodeURIComponent(customer.customer_id)}` }, "View profile")),
      h("div", { style: "display:flex;flex-direction:column;gap:2px" },
        h("span", { style: "font-size:15px;font-weight:600" }, customer.company_name),
        h("span", { class: "small muted", style: "font-size:13px" }, `${customer.contact_name} · ${customer.contact_email}`)),
      h("div", { class: "chips" }, badge(`${customer.plan} plan`), badge(capitalise(customer.account_status), statusTone(customer.account_status))),
      customer.support_notes ? h("div", { class: "form-note" }, customer.support_notes) : null)
      : h("section", { class: "card card-pad" }, h("span", { class: "card-label" }, "Customer"),
        h("span", { class: "small muted", style: "font-size:13px" },
          row.case_type === "escalation" ? "The caller wasn't verified, so this isn't linked to an account. Use the contact details above." : "No customer on file."));

    const relatedCard = related ? h("section", { class: "card card-pad" },
      h("span", { class: "card-label" }, `Related ${related.kind}`),
      h("div", { style: "display:flex;justify-content:space-between;align-items:center;gap:8px" },
        h("span", { style: "font-size:15px;font-weight:600" }, related.reference), badge(capitalise(related.status), statusTone(related.status))),
      h("span", { style: "font-size:13px;color:var(--ink-2)" }, `What the caller hears: ${related.line}`)) : null;

    append(clear(inner), [
      h("div", { style: "display:flex;flex-direction:column;gap:10px" },
        h("h2", { class: "panel-title", id: "panel-title" }, row.title),
        h("div", { class: "chips" }, badge(statusText, statusTone_), badge(`${capitalise(row.priority)} priority`, priorityTone(row.priority)),
          row.case_type === "escalation" && row.verified === false ? badge("Caller not verified", "amber") : null)),
      h("div", { class: "action-row" }, owner,
        can.take && h("button", { type: "button", class: "btn btn-secondary btn-sm", onclick: act("take") }, "Take case"),
        can.resolve && h("button", { type: "button", class: "btn btn-primary btn-sm", onclick: act("resolve") }, "Resolve"),
        can.reopen && h("button", { type: "button", class: "btn btn-secondary btn-sm", onclick: act("reopen") }, "Reopen")),
      row.status === "closed" && row.resolution_note
        ? h("div", { class: "form-note" }, h("span", { class: "strong" }, "Resolution: "), row.resolution_note) : null,
      h("div", { class: "two-col" },
        h("div", { class: "col-main", style: "flex-basis:380px" }, handover, activity),
        h("div", { class: "col-side" },
          fieldRows([
            ["Owner", row.owner ? row.owner.name : "Unassigned"],
            ["Category", capitalise(row.category)],
            ["Callback", callback],
            ["As said", row.preferred_time],
            ["Contact by", contactMethod],
            ["Contact", row.case_type === "escalation" ? contactLine(contact) : null],
            ["Phone", contact.phone],
            ["Reference", row.reference],
            // An escalation and its ticket are one case: show the pair (take, resolve, reopen act on both)
            ["Ticket", row.case_type === "escalation" ? row.ticket_id : null],
            ["Created", when(row.created_at)],
            ["Resolved", row.resolved_at ? when(row.resolved_at) : null],
          ]),
          customerCard, relatedCard))]);
  }

  await reload();
  return { id, reload, close };
}
