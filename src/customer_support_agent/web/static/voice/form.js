// The pre-call form. Browser checks are for the caller's convenience only:
// the backend cleans and validates everything again (api/caller.py).

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
const PHONE = /^(\+|00)\d{8,15}$/;
const NAME_MIN = 2;
const NAME_MAX = 80;

export function readValues(form) {
  const get = (name) => form.elements[name].value.trim();
  return { name: get("name"), email: get("email"), company: get("company"), phone: get("phone") };
}

// field -> error text, for the fields that are wrong
export function check(values) {
  const errors = {};
  if (values.name.length < NAME_MIN || values.name.length > NAME_MAX) errors.name = "Enter your name";
  if (!EMAIL.test(values.email)) errors.email = "Enter a valid email";
  if (values.phone && !PHONE.test(values.phone.replace(/[\s().-]/g, ""))) {
    errors.phone = "Include your country code, for example +234";
  }
  return errors;
}

// What the greeting says ("Hi Amara, …"): the first word of the name, letters only.
export function firstName(name) {
  return (name.split(/\s+/)[0] || "").replace(/[^\p{L}'-]/gu, "").slice(0, 30);
}

// Wires the inputs. A field's error shows once the caller has typed in it and left it, or after they
// press Start call (revealAll). Focus moving on its own (e.g. a browser extension) never shows errors.
export function watchForm(form, onChange) {
  const FIELDS = ["name", "email", "phone"];
  const typed = new Set();
  const left = new Set();
  let revealed = false;

  function show() {
    const values = readValues(form);
    const errors = check(values);
    for (const field of FIELDS) {
      const input = form.elements[field];
      const box = form.querySelector(`#${field}-error`);
      const visible = revealed || (typed.has(field) && left.has(field));
      const message = visible ? errors[field] : undefined;
      box.textContent = message || "";
      box.hidden = !message;
      input.setAttribute("aria-invalid", message ? "true" : "false");
    }
    onChange(Object.keys(errors).length === 0, values);
    return errors;
  }

  form.addEventListener("input", (event) => {
    if (event.target.name) typed.add(event.target.name);
    show();
  });
  form.addEventListener("focusout", (event) => {
    if (event.target.name && typed.has(event.target.name)) left.add(event.target.name);
    show();
  });
  form.addEventListener("submit", (event) => event.preventDefault());
  show();
  return {
    refresh: show,
    // Shows every error; returns the first wrong input (to focus), or null when the form is fine.
    revealAll() {
      revealed = true;
      const errors = show();
      const first = FIELDS.find((field) => errors[field]);
      return first ? form.elements[first] : null;
    },
  };
}
