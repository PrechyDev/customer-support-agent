// Cases: an escalation and its ticket are one case
// Open / Mine / Unassigned / Resolved chips, the table and the side panel.
// URL: /console/cases[/<case_type>/<case_id>][?filter=mine&page=2]. Buttons follow docs/CONSOLE_API.md "Roles"; the
// backend enforces the same rules anyway.

import { api, post, query } from "../api.js";
import { badge, emptyRow, h, toast } from "../dom.js";
import { caseFollowUp, caseStatus, capitalise, priorityTone, when } from "../format.js";
import { PAGE_SIZE, pageFrom, pager } from "../pager.js";
import { openCasePanel } from "./casepanel.js";
import { openResolve } from "./resolve.js";

const TYPES = ["escalation", "ticket"]; // only for the open case's address
const EMPTY = { open: "No open cases.", mine: "No open cases are assigned to you.",
  unassigned: "Every open case has an owner.", resolved: "No resolved cases yet." };
const FILTERS = { open: "Open", mine: "Mine", unassigned: "Unassigned", resolved: "Resolved" };

export function caseActions(row, ctx) {
  const mine = row.owner?.member_id === ctx.me.member_id;
  const open = row.status !== "closed";
  return {
    take: open && !row.owner,
    assign: ctx.permissions.assign_cases, // the backend allows re-assigning a resolved case too
    resolve: open && (ctx.permissions.assign_cases || mine),
    reopen: !open && ctx.permissions.reopen_cases,
  };
}

// Shared by the table and the panel: run an action, then refresh.
export async function runAction(row, kind, ctx, refresh, extra) {
  const base = `/cases/${row.case_type}/${encodeURIComponent(row.case_id)}`;
  try {
    if (kind === "take") await post(`${base}/take`);
    if (kind === "reopen") await post(`${base}/reopen`);
    if (kind === "assign") await post(`${base}/assign`, { member_id: extra });
    if (kind === "resolve") {
      const done = await openResolve(row, (note) => post(`${base}/resolve`, { note }));
      if (!done) return false;
    }
    toast({ take: "You own this case now.", reopen: "Case reopened.", assign: "Owner updated.", resolve: "Case resolved." }[kind]);
    ctx.refreshCounts();
    await refresh();
    return true;
  } catch (error) {
    toast(error.message);
    await refresh();
    return false;
  }
}

export async function ownerControl(row, ctx, onChange) {
  if (!caseActions(row, ctx).assign) {
    const mine = row.owner?.member_id === ctx.me.member_id;
    const text = row.owner ? (mine ? "You" : row.owner.name || "Team member") : "Unassigned";
    return h("span", { class: row.owner ? "" : "due-today" }, text);
  }
  const members = await ctx.activeMembers();
  const select = h("select", { class: "select", "aria-label": `Owner of ${row.case_id}`,
    onclick: (event) => event.stopPropagation(),
    onchange: (event) => { event.stopPropagation(); if (select.value) onChange(select.value); } },
    h("option", { value: "", disabled: Boolean(row.owner), selected: !row.owner }, "Unassigned"),
    members.map((m) => h("option", { value: m.member_id, selected: m.member_id === row.owner?.member_id },
      m.member_id === ctx.me.member_id ? `${m.name || m.email} (you)` : (m.name || m.email))));
  return select;
}

export async function render(container, params, ctx) {
  let state = read(params);
  let panel = null;
  let listRequest = 0; // only the newest list reply is drawn
  const chips = h("div", { class: "chips", role: "group", "aria-label": "Filter" });
  const body = h("div", { class: "table-body" });
  const pages = h("div");
  const table = h("div", { class: "card", style: "overflow:hidden" },
    h("div", { class: "table-row table-head", "aria-hidden": "true" },
      h("span", {}, "Case"), h("span", {}, "Issue"), h("span", {}, "Priority and follow-up"), h("span", {}, "Owner"),
      h("span", {}, "Status"), h("span", {})), body, pages);
  container.replaceChildren(h("div", { class: "page" }, chips, table));

  // /console/cases[?filter=…&page=…] is the list; /console/cases/<type>/<id> also opens that case's panel.
  function read(p) {
    const filter = FILTERS[p.search.get("filter")] ? p.search.get("filter") : "open";
    const open = TYPES.includes(p.parts[0]) && p.parts[1];
    return { filter, page: pageFrom(p.search), type: open ? p.parts[0] : null, id: open ? p.parts[1] : null };
  }

  // A new filter starts at page 1; opening or closing a case keeps the page you're on.
  const href = (filter, row, page = 1) => `/console/cases${row ? `/${row.case_type}/${encodeURIComponent(row.case_id)}` : ""}${query({
    filter: filter !== "open" ? filter : "", page: page > 1 ? page : "" })}`;

  async function loadList() {
    const mine = ++listRequest;
    // no type: escalations and tickets together
    const list = await api(`/cases${query({ filter: state.filter, page: state.page, page_size: PAGE_SIZE })}`);
    if (mine !== listRequest) return; // a newer filter or page was chosen meanwhile
    chips.replaceChildren(...Object.entries(FILTERS).map(([filter, label]) => h("button", {
      type: "button", class: "chip", "aria-pressed": String(filter === state.filter),
      onclick: () => ctx.navigate(href(filter)) }, label, h("span", { class: "n" }, String(list.counts[filter])))));
    const rows = await Promise.all(list.cases.map((row) => tableRow(row)));
    if (mine !== listRequest) return;
    body.replaceChildren(...(rows.length ? rows : [emptyRow(EMPTY[state.filter])]));
    pages.replaceChildren(pager(list.pagination, (page) => ctx.navigate(href(state.filter, null, page))) || "");
  }

  async function tableRow(row) {
    const can = caseActions(row, ctx);
    const [statusText, statusTone] = caseStatus(row.status);
    const followUp = caseFollowUp(row);
    const open = () => ctx.navigate(href(state.filter, row, state.page));
    const act = (kind, extra) => (event) => { event?.stopPropagation(); runAction(row, kind, ctx, refreshAll, extra); };
    const buttons = [
      can.take && h("button", { type: "button", class: "btn btn-secondary btn-xs", onclick: act("take") }, "Take case"),
      can.resolve && h("button", { type: "button", class: "btn btn-primary btn-xs", onclick: act("resolve") }, "Resolve"),
      can.reopen && h("button", { type: "button", class: "btn btn-secondary btn-xs", onclick: act("reopen") }, "Reopen"),
    ];
    const owner = await ownerControl(row, ctx, (memberId) => runAction(row, "assign", ctx, refreshAll, memberId));
    return h("div", { class: "table-row", dataset: { caseId: row.case_id, caseType: row.case_type }, onclick: open },
      h("span", {}, h("button", { type: "button", class: "case-id-button", "aria-label": `Open ${row.case_id}`,
        onclick: (event) => { event.stopPropagation(); open(); } }, row.case_id)),
      h("span", { class: "issue" }, h("span", { style: "line-height:1.4" }, row.title),
        h("span", { class: "small muted" }, `${row.company || "No customer on file"} · opened ${when(row.created_at)}`)),
      h("span", { class: "when" }, badge(capitalise(row.priority), priorityTone(row.priority)),
        h("span", { class: `small follow-up ${followUp.today ? "due-today" : "muted"}`, style: "line-height:1.4" },
          h("span", { class: "strong" }, followUp.label), followUp.detail ? ` ${followUp.detail}` : "")),
      h("span", {}, owner),
      h("span", {}, badge(statusText, statusTone)),
      h("span", { class: "actions" }, buttons));
  }

  async function syncPanel() {
    if (state.id && (!panel || panel.id !== state.id)) {
      panel?.close({ silent: true });
      panel = await openCasePanel(state.type, state.id, ctx, {
        onChanged: () => loadList(),
        onClose: () => { panel = null; ctx.navigate(href(state.filter, null, state.page)); },
      });
    } else if (!state.id && panel) {
      panel.close({ silent: true });
      panel = null;
    }
  }

  async function refreshAll() {
    await loadList();
    if (panel) await panel.reload();
  }

  await loadList();
  await syncPanel();
  return {
    update(params) {
      const next = read(params);
      const listChanged = next.filter !== state.filter || next.page !== state.page;
      state = next;
      (listChanged ? loadList() : Promise.resolve()).then(syncPanel);
      return true;
    },
    refresh: refreshAll, // a new case arrived while this page is open
    destroy() {
      panel?.close({ silent: true });
      panel = null;
    },
  };
}
