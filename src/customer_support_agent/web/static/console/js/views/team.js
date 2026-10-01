// Team (admins and the owner): invite by copy-link, resend, reset link, change role, disable / enable.
// What each row offers mirrors console/permissions.py; the backend checks it again.

import { api, patch, post } from "../api.js";
import { h, toast } from "../dom.js";
import { ROLES, when } from "../format.js";

function canManage(me, member) {
  if (member.member_id === me.member_id || member.role === "superadmin") return false;
  return me.role === "superadmin" ? ["admin", "support"].includes(member.role) : member.role === "support";
}

function linkBox(title, url, expiresAt) {
  const input = h("input", { class: "input", readonly: true, value: url, "aria-label": "Invite link" });
  const copy = h("button", { type: "button", class: "btn btn-primary btn-sm" }, "Copy link");
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(url);
      copy.textContent = "Copied";
    } catch {
      input.select(); // clipboard blocked: select it so Ctrl+C works
      copy.textContent = "Press Ctrl+C";
    }
  });
  return h("div", { class: "link-box", role: "status" },
    h("span", { class: "strong" }, title),
    h("div", { class: "url" }, input, copy),
    h("span", { class: "small" }, `Works once, until ${when(expiresAt)}. It won't be shown again, so copy it now and send it to them.`));
}

export async function render(container, params, ctx) {
  const me = ctx.me;
  const roles = ctx.permissions.manage_admins ? ["support", "admin"] : ["support"];
  const email = h("input", { class: "input", type: "email", placeholder: "name@relaypay.com", "aria-label": "Email to invite", required: true });
  const role = h("select", { class: "select", "aria-label": "Role" }, roles.map((r) => h("option", { value: r }, ROLES[r])));
  const send = h("button", { type: "submit", class: "btn btn-primary btn-sm" }, "Create invite link");
  const error = h("div", { class: "form-error", role: "alert", hidden: true, style: "padding:0 16px 14px" });
  const linkSlot = h("div");
  const members = h("div");

  const form = h("form", { class: "invite-form", novalidate: true, onsubmit: async (event) => {
    event.preventDefault();
    error.hidden = true;
    if (!email.checkValidity() || !email.value.trim()) {
      error.textContent = "Enter a valid email.";
      error.hidden = false;
      email.focus();
      return;
    }
    send.disabled = true;
    try {
      const data = await post("/team/invites", { email: email.value.trim(), role: role.value });
      linkSlot.replaceChildren(linkBox(`Invite link for ${data.member.email}`, data.invite_url, data.expires_at));
      email.value = "";
      ctx.members = null;
      await load();
    } catch (problem) {
      error.textContent = problem.message;
      error.hidden = false;
    } finally {
      send.disabled = false;
    }
  } }, email, role, send);

  container.replaceChildren(h("div", { class: "page", style: "max-width:960px" },
    h("p", { style: "margin:0;font-size:14px;line-height:1.5;color:var(--ink-2);max-width:680px" },
      "Support staff can take unassigned cases and resolve their own. Admins can also assign and reopen cases and manage support staff. ",
      ctx.permissions.manage_admins ? "As the owner, you also manage admins." : "Only the owner can add or change admins."),
    h("section", { class: "card" }, h("div", { class: "card-head" }, h("span", { class: "card-title" }, "Invite a team member")),
      form, error, linkSlot),
    h("section", { class: "card" }, h("div", { class: "card-head" }, h("span", { class: "card-title" }, "Members")), members)));

  async function act(member, run, message) {
    try {
      const data = await run();
      if (data?.invite_url) linkSlot.replaceChildren(linkBox(message.replace("{email}", member.email), data.invite_url, data.expires_at));
      else toast(message.replace("{email}", member.email));
      ctx.members = null;
      await load();
    } catch (problem) {
      toast(problem.message);
    }
  }

  async function load() {
    const data = await api("/team");
    members.replaceChildren(...data.members.map((m) => {
      const self = m.member_id === me.member_id;
      const manageable = canManage(me, m);
      const roleCell = ctx.permissions.manage_admins && manageable
        ? h("select", { class: "select", "aria-label": `Role for ${m.email}`, onchange: (event) =>
          act(m, () => patch(`/team/${m.member_id}`, { role: event.target.value }), "Role updated for {email}.") },
          ["support", "admin"].map((r) => h("option", { value: r, selected: r === m.role }, ROLES[r])))
        : h("span", { class: "small muted", style: "font-size:13px" }, `${ROLES[m.role]}${self ? " (you)" : ""}`);
      const status = { active: ["Active", "status-active"], pending: ["Invite sent", "status-pending"], disabled: ["Disabled", "status-disabled"] }[m.status]
        || [m.status, "status-disabled"];
      const actions = manageable ? [
        m.status === "pending" && h("button", { type: "button", class: "btn btn-secondary btn-xs",
          onclick: () => act(m, () => post(`/team/${m.member_id}/resend`), "New invite link for {email}") }, "Resend invite"),
        m.status === "active" && h("button", { type: "button", class: "btn btn-secondary btn-xs",
          onclick: () => act(m, () => post(`/team/${m.member_id}/reset-link`), "Password reset link for {email}") }, "Reset link"),
        m.status !== "disabled"
          ? h("button", { type: "button", class: "btn btn-secondary btn-xs",
            onclick: () => { if (confirm(`Disable ${m.name || m.email}? They'll be signed out straight away.`)) act(m, () => patch(`/team/${m.member_id}`, { status: "disabled" }), "{email} disabled."); } }, "Disable")
          : h("button", { type: "button", class: "btn btn-secondary btn-xs",
            onclick: () => act(m, () => patch(`/team/${m.member_id}`, { status: "active" }), "{email} enabled.") }, "Enable"),
      ] : [];
      return h("div", { class: "member-row" },
        h("span", { style: "display:flex;flex-direction:column;gap:2px;min-width:0" },
          h("span", { class: "strong ellipsis" }, m.name || "Not set up yet"),
          h("span", { class: "small muted ellipsis" }, m.email + (m.invited_by_name ? ` · invited by ${m.invited_by_name}` : ""))),
        roleCell,
        h("span", { class: status[1] }, status[0]),
        h("span", { class: "acts" }, actions));
    }));
  }
  await load();
  return null;
}
