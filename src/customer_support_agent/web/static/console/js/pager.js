// Pages for long lists (docs/CONSOLE_API.md "Pagination"). The page lives in the URL (?page=2), so Back and
// refresh keep your place; changing a search or filter goes back to page 1 (the links simply leave page out).
// A reply without "pagination" (the API before paging) gets no pager, and the list works as before.

import { h } from "./dom.js";

export const PAGE_SIZE = 25;

export function pageFrom(search) {
  const page = Number.parseInt(search.get("page") || "1", 10);
  return Number.isInteger(page) && page > 0 ? Math.min(page, 100000) : 1;
}

// pagination: {page, page_size, total} from the API; go(page) navigates.
export function pager(pagination, go) {
  if (!pagination || typeof pagination.total !== "number") return null;
  const { page, page_size: size, total } = pagination;
  const pages = Math.max(1, Math.ceil(total / size));
  if (pages === 1 && page === 1) return null; // everything fits on one page
  const first = (page - 1) * size + 1;
  const last = Math.min(page * size, total);
  const summary = first > total ? `Page ${page} of ${pages}: nothing here` : `Showing ${first}–${last} of ${total}`;
  return h("nav", { class: "pager", "aria-label": "Pages" },
    h("span", { class: "small muted", "aria-live": "polite" }, summary),
    h("span", { class: "pager-buttons" },
      h("button", { type: "button", class: "btn btn-secondary btn-xs", disabled: page <= 1,
        onclick: () => go(Math.min(page - 1, pages)) }, "Previous"),
      h("button", { type: "button", class: "btn btn-secondary btn-xs", disabled: page >= pages,
        onclick: () => go(page + 1) }, "Next")));
}
