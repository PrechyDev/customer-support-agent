// Support console app: routing, the shell (sidebar + top bar), and who's signed in.
// Each screen is a module with render(container, params, ctx) -> { update?(params), destroy?() }.

import { api, post, whenSignedOut } from "./api.js";
import { clear, h, icon, initials } from "./dom.js";
import { ROLES } from "./format.js";
import { createPing } from "./ping.js";
import * as auth from "./views/auth.js";
import * as dashboard from "./views/dashboard.js";
import * as cases from "./views/cases.js";
import * as conversations from "./views/conversations.js";
import * as customers from "./views/customers.js";
import * as analytics from "./views/analytics.js";
import * as team from "./views/team.js";

const root = document.getElementById("app");
const VIEWS = {
  dashboard: { module: dashboard, title: "Dashboard" },
  cases: { module: cases, title: "Cases" },
  conversations: { module: conversations, title: "Conversations" },
  customers: { module: customers, title: "Customers" },
  analytics: { module: analytics, title: "Analytics" },
  team: { module: team, title: "Team", admin: true },
};

const ctx = {
  me: null,
  permissions: {},
  navigate,
  setTitle: (text) => {
    if (shell) shell.title.textContent = text;
    document.title = `${text} · RelayPay Support Console`;
  },
  refreshCounts,
  members: null, // active team members, loaded once for the owner pickers (admins only)
  async activeMembers() {
    if (!ctx.permissions.assign_cases) return [];
    if (!ctx.members) {
      ctx.members = api("/team").then((data) => data.members.filter((m) => m.status === "active"))
        .catch(() => { ctx.members = null; return []; });
    }
    return ctx.members;
  },
};

let shell = null;
let current = { key: null, instance: null };
let ping = null;

// --- routing --------------------------------------------------------------------------------
function parse(pathname) {
  const parts = pathname.replace(/^\/console\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  const search = new URLSearchParams(location.search);
  if (parts[0] === "invite") return { key: "invite", params: { token: parts[1] || "" } };
  const key = VIEWS[parts[0]] ? parts[0] : "dashboard";
  return { key, params: { parts: parts.slice(1), search } };
}

export function navigate(path, { replace = false } = {}) {
  if (path === location.pathname + location.search) return route();
  history[replace ? "replaceState" : "pushState"](null, "", path);
  return route();
}

async function route() {
  const { key, params } = parse(location.pathname);
  if (key === "invite") {
    teardown();
    return auth.renderInvite(root, params.token, { onSignedIn: () => startApp("/console") });
  }
  if (!ctx.me && !(await loadMe())) return;
  const view = VIEWS[key];
  if (view.admin && !ctx.permissions.manage_team) return navigate("/console", { replace: true });
  ensureShell();
  markNav(key);
  closeMenu();
  if (current.key === key && current.instance?.update?.(params)) return;
  current.instance?.destroy?.();
  ctx.setTitle(view.title);
  const container = clear(shell.content);
  current = { key, instance: null };
  try {
    current.instance = (await view.module.render(container, params, ctx)) || null;
  } catch (error) {
    if (error?.status !== 401) { // a 401 already sent the user to sign in
      console.error("[console] view failed", error);
      container.replaceChildren(h("div", { class: "page" },
        h("div", { class: "notice", role: "alert" }, error?.message || "This page couldn't load. Please try again.")));
    }
  }
}

async function loadMe() {
  try {
    const data = await api("/me");
    ctx.me = data.member;
    ctx.permissions = data.permissions;
    return true;
  } catch (error) {
    if (error.status === 401) showSignIn();
    else root.replaceChildren(h("div", { class: "auth" }, h("div", { class: "auth-card" },
      h("h1", {}, "The console isn't available"), h("p", {}, error.message))));
    return false;
  }
}

function showSignIn() {
  teardown();
  auth.renderSignIn(root, { onSignedIn: () => startApp() });
}

function startApp(path) {
  ctx.me = null;
  ctx.members = null;
  if (path) history.replaceState(null, "", path);
  route();
}

function teardown() {
  current.instance?.destroy?.();
  current = { key: null, instance: null };
  ping?.stop();
  ping = null;
  shell = null;
  ctx.me = null;
  ctx.members = null;
}

whenSignedOut(() => {
  if (shell) showSignIn();
});

// --- shell ----------------------------------------------------------------------------------
function navItem(key, label) {
  const count = h("span", { class: "nav-count" });
  const fresh = h("span", { class: "nav-new", hidden: true });
  const link = h("a", { class: "nav-item", href: key === "dashboard" ? "/console" : `/console/${key}`, dataset: { view: key } },
    h("span", {}, label), h("span", { class: "nav-badges" }, fresh, " ", count));
  return { link, count, fresh };
}

function ensureShell() {
  if (shell) return;
  const items = {
    dashboard: navItem("dashboard", "Dashboard"),
    cases: navItem("cases", "Cases"),
    conversations: navItem("conversations", "Conversations"),
    customers: navItem("customers", "Customers"),
    analytics: navItem("analytics", "Analytics"),
  };
  const groups = [h("div", { class: "nav-group" }, h("div", { class: "nav-label" }, "Support console"),
    ...Object.values(items).map((item) => item.link))];
  if (ctx.permissions.manage_team) {
    items.team = navItem("team", "Team");
    groups.push(h("div", { class: "nav-group" }, h("div", { class: "nav-label" }, "Admin"), items.team.link));
  }
  const title = h("h1", {}, "");
  const live = h("span", { class: "online-text" }, "Assistant online");
  const soundSlot = h("span");
  const content = h("main", { class: "content", id: "content", tabindex: "-1" });
  const signOut = h("button", { type: "button", class: "link-button", onclick: signOutNow }, "Sign out");
  const menuButton = h("button", { type: "button", class: "icon-button menu-button", "aria-label": "Open menu",
    "aria-expanded": "false", onclick: () => toggleMenu() }, icon("menu", 20));
  const element = h("div", { class: "shell" },
    h("aside", { class: "sidebar", id: "sidebar", "aria-label": "Main" },
      h("div", { class: "sidebar-head" }, h("img", { src: "/static/shared/relaypay-logo.png", alt: "RelayPay", width: 108, height: 20 })),
      h("nav", { class: "nav" }, groups),
      h("div", { class: "sidebar-foot" }, h("div", { class: "avatar" }, initials(ctx.me.name || ctx.me.email)),
        h("div", { class: "me" }, h("span", { class: "name ellipsis" }, ctx.me.name || ctx.me.email),
          h("span", { class: "role" }, ROLES[ctx.me.role] || ctx.me.role), signOut))),
    h("div", { class: "scrim", onclick: () => toggleMenu(false) }),
    h("div", { class: "main" },
      h("header", { class: "topbar" },
        h("div", { class: "online" }, menuButton, title),
        h("div", { class: "topbar-right" }, soundSlot,
          h("span", { class: "online" }, h("span", { class: "online-dot", "aria-hidden": "true" }), live))),
      content));
  root.replaceChildren(element);
  shell = { element, title, live, content, items, menuButton };
  ping = createPing({ soundSlot, onNew: (count) => markNew(count) });
  ping.start();
  refreshCounts();
}

function markNav(key) {
  for (const [name, item] of Object.entries(shell.items)) {
    if (name === key) item.link.setAttribute("aria-current", "page");
    else item.link.removeAttribute("aria-current");
  }
  if (key === "cases") markNew(0);
}

function markNew(count) {
  const badge = shell?.items.cases.fresh;
  if (!badge) return;
  if (count > 0 && current.key !== "cases") {
    badge.textContent = `${count} new`;
    badge.hidden = false;
  } else {
    badge.hidden = true;
    ping?.seen();
    if (count > 0) current.instance?.refresh?.(); // on Cases already: show the new case in the table
  }
  if (count > 0) refreshCounts();
}

async function refreshCounts() {
  if (!shell) return;
  try {
    const { kpis } = await api("/summary");
    shell.items.cases.count.textContent = kpis.open_cases ? String(kpis.open_cases) : "";
    shell.live.textContent = kpis.live_now ? `Assistant online · ${kpis.live_now} live` : "Assistant online";
  } catch (error) {
    console.info("[console] counts not refreshed", error?.code);
  }
}

function toggleMenu(open) {
  if (!shell) return;
  const isOpen = open ?? !shell.element.classList.contains("menu-open");
  shell.element.classList.toggle("menu-open", isOpen);
  shell.menuButton.setAttribute("aria-expanded", String(isOpen));
}

function closeMenu() {
  toggleMenu(false);
}

async function signOutNow() {
  try {
    await post("/logout");
  } catch (error) {
    console.info("[console] sign-out request failed", error?.code);
  }
  showSignIn();
}

// Internal links: no full page reload.
document.addEventListener("click", (event) => {
  const link = event.target.closest("a[href^='/console']");
  if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || link.target) return;
  event.preventDefault();
  navigate(link.getAttribute("href"));
});
window.addEventListener("popstate", route);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeMenu();
});

route();
