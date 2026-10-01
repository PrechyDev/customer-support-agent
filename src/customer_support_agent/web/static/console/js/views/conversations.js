// Conversations: list (search + outcome chips) and detail (summary, what the assistant did, transcript).
// URL: /console/conversations[/<id>][?outcome=…&search=…&page=…]

import { api, query } from "../api.js";
import { badge, debounce, emptyRow, h } from "../dom.js";
import { OUTCOMES, clockTime, duration, noteView, ratingLabel, when, conversationBadge } from "../format.js";
import { PAGE_SIZE, pageFrom, pager } from "../pager.js";
import { caseLink } from "./dashboard.js";

export async function render(container, params, ctx) {
  let state = read(params);
  const search = h("input", { class: "input", type: "search", placeholder: "Search caller or topic", "aria-label": "Search conversations",
    value: state.search });
  const chips = h("div", { class: "chips", role: "group", "aria-label": "Outcome" });
  const items = h("div", { class: "split-items", role: "list" });
  const detail = h("div", { class: "split-detail" });
  const split = h("div", { class: "split" },
    h("div", { class: "split-list" }, h("div", { class: "split-tools" }, search, chips), items), detail);
  container.replaceChildren(split);
  let listRequest = 0;
  let detailRequest = 0; // only the newest reply is drawn

  function read(p) {
    return { id: p.parts[0] || null, outcome: OUTCOMES[p.search.get("outcome")] ? p.search.get("outcome") : "",
      search: (p.search.get("search") || "").slice(0, 100), page: pageFrom(p.search) };
  }

  // A new search or outcome starts again at page 1 (page is only kept when it's passed in).
  const href = (id, s = state) => `/console/conversations${id ? `/${encodeURIComponent(id)}` : ""}${query({
    outcome: s.outcome, search: s.search, page: s.page > 1 ? s.page : "" })}`;

  async function loadList() {
    const mine = ++listRequest;
    const data = await api(`/conversations${query({ search: state.search, outcome: state.outcome, page: state.page, page_size: PAGE_SIZE })}`);
    if (mine !== listRequest) return;
    chips.replaceChildren(...[["", "All", data.counts.all], ...Object.entries(OUTCOMES).map(([key, [label]]) => [key, label, data.counts[key]])]
      .map(([key, label, n]) => h("button", { type: "button", class: "chip", "aria-pressed": String(key === state.outcome),
        onclick: () => ctx.navigate(href(state.id, { ...state, outcome: key, page: 1 })) }, label, h("span", { class: "n" }, String(n ?? 0)))));
    const pages = pager(data.pagination, (page) => {
      ctx.navigate(href(state.id, { ...state, page }));
      items.scrollTop = 0;
    });
    items.replaceChildren(...(data.conversations.length ? data.conversations.map((row) => h("a", {
      class: "conv-item", role: "listitem", href: href(row.conversation_id), "aria-current": String(row.conversation_id === state.id) },
      h("div", { class: "top" }, h("span", { class: "strong ellipsis", style: "font-size:14px" }, row.caller),
        h("span", { class: "small muted nowrap" }, when(row.started_at))),
      h("div", { class: "summary" }, row.summary || "No summary yet."),
      h("div", { class: "foot" }, badge(...conversationBadge(row)),
        h("span", {}, `Voice · ${duration(row.duration_s)}`))))
      : [emptyRow("No conversations match.")]), pages || "");
  }

  let allChecks = false; // "Show all checks": also the routine notes ("no facts stated")
  const showAll = h("button", { type: "button", class: "link-button", "aria-pressed": "false" }, "Show all checks");
  showAll.addEventListener("click", () => {
    allChecks = !allChecks;
    showAll.textContent = allChecks ? "Hide routine checks" : "Show all checks";
    showAll.setAttribute("aria-pressed", String(allChecks));
    for (const note of detail.querySelectorAll(".note.routine")) note.hidden = !allChecks;
  });

  // The backend's check of each reply: flags stand out, sources are quiet, routine notes wait for the toggle.
  function noteLine(note) {
    const view = noteView(note);
    if (!view) return null;
    return h("span", { class: `note ${view.kind}`, hidden: view.kind === "routine" && !allChecks, title: view.raw }, view.text);
  }

  async function loadDetail() {
    const mine = ++detailRequest;
    split.classList.toggle("has-detail", Boolean(state.id));
    if (!state.id) {
      detail.replaceChildren(emptyRow("Choose a conversation to see what happened."));
      return;
    }
    detail.replaceChildren(h("div", { class: "detail" }, h("p", { class: "muted" }, "Loading…")));
    let data;
    try {
      data = await api(`/conversations/${encodeURIComponent(state.id)}`);
    } catch (error) {
      if (mine === detailRequest) detail.replaceChildren(h("div", { class: "detail" }, h("div", { class: "notice", role: "alert" }, error.message)));
      return;
    }
    if (mine === detailRequest) drawDetail(data); // another conversation was chosen meanwhile
  }

  function drawDetail({ conversation: c, transcript, actions, cases, searches }) {
    const links = [
      ...cases.map((row) => h("a", { class: "link-chip", href: caseLink(row) },
        h("span", { class: "k" }, row.case_type === "escalation" ? "Escalation" : "Ticket"), h("span", { class: "strong" }, row.case_id))),
      c.verified_customer_id ? h("a", { class: "link-chip", href: `/console/customers/${encodeURIComponent(c.verified_customer_id)}` },
        h("span", { class: "k" }, "Customer"), h("span", { class: "strong" }, c.caller)) : null,
    ].filter(Boolean);
    const steps = [
      ...actions.map((a) => ({ when: a.when, label: a.label, detail: a.detail, ok: a.ok })),
      ...searches.map((s) => ({ when: null, label: `Searched help articles for "${s.query}"`,
        detail: s.chunks.length ? `Found: ${s.chunks.join(", ")}` : "Nothing matched", ok: true })),
    ];
    const form = [c.form?.name, c.form?.email].filter(Boolean).join(" · ");
    detail.replaceChildren(h("div", { class: "detail" },
      h("a", { class: "back-link mobile-only", href: href(null) }, "← All conversations"),
      h("div", { style: "display:flex;flex-direction:column;gap:8px" },
        h("div", { style: "display:flex;align-items:center;gap:10px;flex-wrap:wrap" },
          h("h2", {}, c.caller), badge(...conversationBadge(c))),
        h("div", { class: "meta-line" }, h("span", {}, "Voice"), h("span", {}, when(c.started_at)),
          h("span", {}, duration(c.duration_s)), h("span", {}, ratingLabel(c.rating))),
        form ? h("div", { class: "small muted" }, `Pre-call form: ${form}${c.verified_customer_id ? "" : " (not verified)"}`) : null),
      h("section", { class: "card card-pad" }, h("div", { class: "card-label" }, "Summary"),
        h("div", { class: "text" }, c.summary || "No summary was recorded for this call."),
        links.length ? h("div", { class: "chips" }, links) : null),
      steps.length ? h("section", { class: "card" },
        h("div", { class: "card-head" }, h("span", { class: "card-title" }, "What the assistant did")),
        steps.map((s) => h("div", { class: "step" }, h("span", { class: "muted" }, s.when ? clockTime(s.when) : ""),
          h("span", {}, h("span", { class: "strong" }, s.label), s.detail ? h("span", { class: "muted" }, ` ${s.detail}`) : null),
          h("span", { class: s.ok ? "ok" : "failed" }, s.ok ? "Done" : "Failed")))) : null,
      h("section", { class: "card" },
        h("div", { class: "card-head" }, h("span", { class: "card-title" }, "Transcript"),
          transcript.some((t) => noteView(t.note)?.kind === "routine") ? showAll : null),
        transcript.length ? h("div", { class: "turns" }, transcript.map((t) => h("div", { class: "turn" },
          h("span", { class: "time" }, clockTime(t.when)),
          h("span", { class: `who ${t.speaker}` }, t.speaker === "caller" ? "Caller" : "Assistant"),
          h("span", { class: "text" }, t.text, noteLine(t.note)))))
          : emptyRow("The caller disconnected before speaking."))));
    ctx.setTitle(`Conversation · ${c.caller}`);
  }

  search.addEventListener("input", debounce(() => {
    ctx.navigate(href(state.id, { ...state, search: search.value.trim(), page: 1 }), { replace: true });
  }, 300));

  await Promise.all([loadList(), loadDetail()]);
  return {
    update(params) {
      const next = read(params);
      const listChanged = next.search !== state.search || next.outcome !== state.outcome || next.page !== state.page;
      const detailChanged = next.id !== state.id;
      state = next;
      if (listChanged) loadList();
      else for (const item of items.querySelectorAll(".conv-item")) {
        item.setAttribute("aria-current", String(item.getAttribute("href").split("?")[0].endsWith(`/${encodeURIComponent(state.id)}`)));
      }
      if (detailChanged) {
        loadDetail();
        if (!state.id) ctx.setTitle("Conversations");
      }
      return true;
    },
  };
}
