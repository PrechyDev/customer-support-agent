// Sign in, and the invite / password-reset screen (/console/invite/<token>).

import { api, post } from "../api.js";
import { h, icon } from "../dom.js";

const ROLE_PHRASE = { superadmin: "the owner", admin: "an admin", support: "support staff" };

// Show / hide for a password input: a real button after the input (so Tab reaches it next and Enter or Space
// work it), never a submit button. Switching keeps the value and the cursor.
function passwordToggle(input) {
  const button = h("button", { type: "button", class: "password-toggle", "aria-controls": input.id,
    // a mouse click leaves focus (and the cursor) in the input, so typing carries on
    onmousedown: (event) => event.preventDefault() });

  function show(visible) {
    const { selectionStart: start, selectionEnd: end } = input;
    input.type = visible ? "text" : "password";
    if (start !== null) input.setSelectionRange(start, end); // keep the cursor where it was
    button.setAttribute("aria-label", visible ? "Hide password" : "Show password");
    button.setAttribute("aria-pressed", String(visible));
    button.replaceChildren(icon(visible ? "eyeOff" : "eye", 18));
  }

  button.addEventListener("click", () => show(input.type === "password"));
  show(false);
  return { element: h("div", { class: "password-wrap" }, input, button), hide: () => show(false) };
}

function field(id, label, attrs) {
  const input = h("input", { id, name: id, class: "input", style: "height:44px;font-size:14px", ...attrs,
    "aria-describedby": `${id}-error` });
  const error = h("div", { class: "form-error", id: `${id}-error`, hidden: true });
  const toggle = attrs.type === "password" ? passwordToggle(input) : null;
  return { input, error, hide: toggle ? toggle.hide : () => {},
    element: h("div", { class: "field" }, h("label", { for: id }, label), toggle ? toggle.element : input, error) };
}

function setError(f, message) {
  f.error.textContent = message || "";
  f.error.hidden = !message;
  f.input.setAttribute("aria-invalid", message ? "true" : "false");
}

function frame(...card) {
  return h("div", { class: "auth" },
    h("img", { class: "logo", src: "/static/shared/relaypay-logo.png", alt: "RelayPay", width: 162, height: 30 }),
    h("div", { class: "auth-card" }, ...card));
}

export function renderSignIn(root, { onSignedIn }) {
  document.title = "Sign in · RelayPay Support Console";
  const email = field("email", "Work email", { type: "email", autocomplete: "username", required: true, placeholder: "you@relaypay.com" });
  const password = field("password", "Password", { type: "password", autocomplete: "current-password", required: true });
  const error = h("div", { class: "form-error", role: "alert", hidden: true });
  const help = h("div", { class: "form-note", hidden: true }, "Ask an admin to send you a reset link.");
  const submit = h("button", { type: "submit", class: "btn btn-primary btn-block" }, "Sign in");

  const form = h("form", { class: "auth-form", novalidate: true, style: "display:flex;flex-direction:column;gap:18px",
    onsubmit: async (event) => {
      event.preventDefault();
      password.hide(); // after any submit (success, error or a missing field) the password is hidden again
      error.hidden = true;
      if (!email.input.value.trim() || !password.input.value) {
        error.textContent = "Enter your work email and password.";
        error.hidden = false;
        return;
      }
      submit.disabled = true;
      try {
        await post("/login", { email: email.input.value.trim(), password: password.input.value });
        onSignedIn();
      } catch (problem) {
        error.textContent = problem.message;
        error.hidden = false;
        password.input.value = "";
        password.input.focus();
      } finally {
        submit.disabled = false;
      }
    } },
    email.element, password.element, error, submit,
    h("button", { type: "button", class: "link-button", onclick: () => { help.hidden = false; } }, "Forgot password?"),
    help);

  root.replaceChildren(frame(
    h("div", { class: "head" }, h("h1", {}, "Sign in to Support Console"), h("p", {}, "For RelayPay team members.")),
    form));
  email.input.focus();
}

export async function renderInvite(root, token, { onSignedIn }) {
  document.title = "Set up your account · RelayPay Support Console";
  root.replaceChildren(frame(h("p", {}, "Checking your link…")));
  let link;
  try {
    link = await api(`/invites/${encodeURIComponent(token)}`);
  } catch (problem) {
    root.replaceChildren(frame(
      h("div", { class: "head" }, h("h1", {}, "This link doesn't work"), h("p", {}, problem.message)),
      h("a", { href: "/console", class: "btn btn-secondary btn-block" }, "Go to sign in")));
    return;
  }
  const reset = link.kind === "reset";
  const name = field("name", "Your name", { type: "text", autocomplete: "name", maxlength: 80, required: true });
  const password = field("password", reset ? "New password" : "Password",
    { type: "password", autocomplete: "new-password", minlength: 8, maxlength: 128, required: true });
  const confirm = field("confirm_password", "Confirm password",
    { type: "password", autocomplete: "new-password", maxlength: 128, required: true });
  const hint = h("div", { class: "hint" }, "At least 8 characters, and not your email.");
  password.element.append(hint);
  const error = h("div", { class: "form-error", role: "alert", hidden: true });
  const submit = h("button", { type: "submit", class: "btn btn-primary btn-block" }, reset ? "Set new password" : "Create account");

  const form = h("form", { novalidate: true, style: "display:flex;flex-direction:column;gap:16px", onsubmit: async (event) => {
    event.preventDefault();
    password.hide(); // after any submit, both passwords are hidden again
    confirm.hide();
    error.hidden = true;
    for (const f of [name, password, confirm]) setError(f, "");
    const local = {};
    if (name.input.value.trim().length < 2) local.name = "Enter your name.";
    if (password.input.value.length < 8) local.password = "Use at least 8 characters.";
    if (confirm.input.value !== password.input.value) local.confirm_password = "The passwords don't match.";
    const all = { name, password, confirm_password: confirm };
    if (Object.keys(local).length) {
      for (const [key, message] of Object.entries(local)) setError(all[key], message);
      all[Object.keys(local)[0]].input.focus();
      return;
    }
    submit.disabled = true;
    try {
      await post(`/invites/${encodeURIComponent(token)}/accept`,
        { name: name.input.value.trim(), password: password.input.value, confirm_password: confirm.input.value });
      onSignedIn();
    } catch (problem) {
      const fields = Object.entries(problem.fields || {});
      for (const [key, message] of fields) if (all[key]) setError(all[key], message);
      if (!fields.length) {
        error.textContent = problem.message;
        error.hidden = false;
      }
    } finally {
      submit.disabled = false;
    }
  } }, name.element, password.element, confirm.element, error, submit);

  root.replaceChildren(frame(
    h("div", { class: "head" },
      h("h1", {}, reset ? "Set a new password" : "Set up your account"),
      h("p", {}, reset ? `For ${link.email}.` : `You've been invited to the RelayPay Support Console as ${ROLE_PHRASE[link.role] || "a team member"} (${link.email}).`)),
    form));
  name.input.focus();
}
