// Customers: list with search, and a profile (cases, payments and payouts, conversations, fields, support notes).

import { api, query } from "../api.js";
import { badge, debounce, emptyRow, h } from "../dom.js";
import { capitalise, caseStatus, duration, money, shortDate, statusTone, when, conversationBadge } from "../format.js";
import { PAGE_SIZE, pageFrom, pager } from "../pager.js";
import { caseLink } from "./dashboard.js";

export async function render(container, params, ctx) {
  let id = params.parts[0] || null;
  let request = 0; // only the newest draw may touch the page

  async function draw() {
    const mine = ++request;
    const current = () => mine === request;
    if (id) await profile(container, id, ctx, current);
    else await list(container, ctx, params.search.get("search") || "", pageFrom(params.search), current);
  }
  await draw();
  return {
    update(next) {
      params = next; // the list reads its search and page from these
      const nextId = next.parts[0] || null;
      if (nextId === id && !nextId) return false; // search change on the list: re-render normally
      id = nextId;
      ctx.setTitle("Customers");
      draw();
      return true;
    },
  };
}

async function list(container, ctx, initial, initialPage, current = () => true) {
  let page = initialPage;
  const search = h("input", { class: "input", type: "search", placeholder: "Search company, contact or email",
    "aria-label": "Search customers", style: "width:320px;max-width:100%", value: initial });
  const body = h("div", { class: "cust-body" });
  const pages = h("div");
  container.replaceChildren(h("div", { class: "page" }, search,
    h("div", { class: "card", style: "overflow:hidden" },
      h("div", { class: "cust-row table-head cust-head", "aria-hidden": "true" },
        ["Company", "Contact", "Plan", "Account", "Region", "Open cases", "Calls"].map((t) => h("span", {}, t))), body, pages)));

  const href = (p) => `/console/customers${query({ search: search.value.trim(), page: p > 1 ? p : "" })}`;
  let searchRequest = 0;
  async function load() {
    const mine = ++searchRequest;
    const data = await api(`/customers${query({ search: search.value.trim(), page, page_size: PAGE_SIZE })}`);
    if (mine !== searchRequest || !current()) return;
    pages.replaceChildren(pager(data.pagination, (p) => ctx.navigate(href(p))) || "");
    body.replaceChildren(...(data.customers.length ? data.customers.map((c) => h("a", {
      class: "cust-row", href: `/console/customers/${encodeURIComponent(c.customer_id)}` },
      h("span", { class: "strong" }, c.company),
      h("span", { style: "display:flex;flex-direction:column;gap:2px;min-width:0" }, h("span", {}, c.contact_name),
        h("span", { class: "small muted ellipsis" }, c.contact_email)),
      h("span", {}, c.plan),
      h("span", {}, badge(capitalise(c.account_status), statusTone(c.account_status))),
      h("span", { class: "muted" }, c.region),
      h("span", {}, String(c.open_cases)),
      h("span", { class: "muted" }, String(c.calls)))) : [emptyRow("No customers match.")]));
  }
  search.addEventListener("input", debounce(() => {
    page = 1; // a new search starts at the first page
    history.replaceState(null, "", href(1));
    load();
  }, 300));
  await load();
}

async function profile(container, id, ctx, current = () => true) {
  const data = await api(`/customers/${encodeURIComponent(id)}`);
  if (!current()) return; // another customer was chosen meanwhile
  const c = data.customer;
  ctx.setTitle(c.company_name);
  const openCases = data.cases.filter((k) => k.status !== "closed");
  const payoutsByTxn = new Map(data.payouts.map((p) => [p.transaction_id, p]));
  const money_ = [
    ...data.transactions.map((t) => ({ id: t.transaction_id, what: capitalise(t.type),
      note: `${shortDate(t.created_at)}${payoutsByTxn.has(t.transaction_id) ? ` · payout ${payoutsByTxn.get(t.transaction_id).payout_id}` : ""}`,
      amount: money(t.amount, t.currency), status: t.status })),
    ...data.payouts.map((p) => ({ id: p.payout_id, what: "Payout", note: `For ${p.transaction_id}${p.scheduled_for ? ` · scheduled ${shortDate(p.scheduled_for)}` : ""}`,
      amount: money(p.amount, p.currency), status: p.status })),
  ];
  container.replaceChildren(h("div", { class: "page", style: "max-width:1200px" },
    h("a", { class: "back-link", href: "/console/customers" }, "← All customers"),
    h("div", { style: "display:flex;flex-direction:column;gap:8px" },
      h("h2", { class: "page-title" }, c.company_name),
      h("div", { class: "meta-line" }, badge(capitalise(c.account_status), statusTone(c.account_status)),
        h("span", {}, `${c.plan} plan`), h("span", {}, "·"), h("span", {}, c.region), h("span", {}, "·"), h("span", {}, c.customer_id))),
    h("div", { class: "two-col" },
      h("div", { class: "col-main" },
        h("section", { class: "card" }, h("div", { class: "card-head" }, h("span", { class: "card-title" }, "Open cases")),
          openCases.length ? openCases.map((k) => {
            const [text, tone] = caseStatus(k.status);
            return h("a", { class: "list-row", href: caseLink(k) },
              h("span", { class: "stack" }, h("span", { class: "title" }, k.title),
                h("span", { class: "meta" }, [k.case_id, k.owner ? k.owner.name : "Unassigned", `opened ${when(k.created_at)}`].join(" · "))),
              badge(text, tone));
          }) : emptyRow("No open cases.")),
        h("section", { class: "card" }, h("div", { class: "card-head" }, h("span", { class: "card-title" }, "Recent payments and payouts")),
          money_.length ? money_.map((m) => h("div", { class: "money-row" },
            h("span", { class: "strong" }, m.id),
            h("span", { style: "display:flex;flex-direction:column;gap:2px;min-width:0" }, h("span", {}, m.what), h("span", { class: "small muted" }, m.note)),
            h("span", { class: "right" }, m.amount),
            h("span", { class: "right" }, badge(capitalise(m.status), statusTone(m.status))))) : emptyRow("No recent activity.")),
        h("section", { class: "card" }, h("div", { class: "card-head" }, h("span", { class: "card-title" }, "Conversations")),
          data.conversations.length ? data.conversations.map((v) => h("a", { class: "list-row", href: `/console/conversations/${encodeURIComponent(v.conversation_id)}` },
            h("span", { class: "stack" }, h("span", { style: "font-size:14px" }, v.summary || "No summary yet."),
              h("span", { class: "meta" }, `${when(v.started_at)} · Voice · ${duration(v.duration_s)}`)),
            badge(...conversationBadge(v)))) : emptyRow("No conversations yet."))),
      h("div", { class: "col-side" },
        h("section", { class: "card fields" }, [["Contact", c.contact_name], ["Email", c.contact_email], ["Plan", c.plan],
          ["Verification", capitalise(c.kyc_status)], ["Region", c.region], ["Customer ID", c.customer_id]]
          .map(([label, value]) => h("div", { class: "field-row" }, h("span", {}, label), h("span", {}, value || "–")))),
        h("section", { class: "card card-pad" }, h("span", { class: "card-label" }, "Support notes"),
          h("span", { class: "text" }, c.support_notes || "No notes."),
          h("span", { class: "small muted" }, "Internal. The assistant never reads these aloud."))))));
}
