// The "Resolve" dialog: a required note (1–500 characters), saved to the case history.
// Resolves to true when the case was resolved, false when cancelled.

import { h } from "../dom.js";

const MAX = 500;

export function openResolve(row, save) {
  return new Promise((resolve) => {
    const before = document.activeElement;
    const note = h("textarea", { class: "textarea", id: "resolve-note", rows: 3, maxlength: MAX,
      placeholder: "e.g. Refund approved and confirmed with the customer by phone", "aria-describedby": "resolve-help resolve-error" });
    const error = h("div", { class: "form-error", id: "resolve-error", role: "alert", hidden: true });
    const confirm = h("button", { type: "button", class: "btn btn-primary btn-sm", disabled: true }, "Resolve case");
    const cancel = h("button", { type: "button", class: "btn btn-secondary btn-sm" }, "Cancel");
    const dialog = h("div", { class: "modal", role: "dialog", "aria-modal": "true", "aria-labelledby": "resolve-title" },
      h("h2", { id: "resolve-title" }, `Resolve ${row.case_id}`),
      h("p", { id: "resolve-help" }, "Add a short note on how this was resolved. It is saved to the case history."),
      h("label", { for: "resolve-note", class: "visually-hidden" }, "Resolution note"),
      note, error, h("div", { class: "row" }, cancel, confirm));
    const backdrop = h("div", { class: "backdrop modal-backdrop" });

    function close(done) {
      document.removeEventListener("keydown", onKey, true);
      backdrop.remove();
      dialog.remove();
      before?.focus?.();
      resolve(done);
    }

    function onKey(event) {
      if (event.key === "Escape") {
        event.stopPropagation();
        close(false);
      }
      if (event.key === "Tab") { // keep focus inside the dialog
        const items = [note, cancel, confirm].filter((el) => !el.disabled);
        const i = items.indexOf(document.activeElement);
        if (event.shiftKey && i <= 0) { event.preventDefault(); items[items.length - 1].focus(); }
        else if (!event.shiftKey && i === items.length - 1) { event.preventDefault(); items[0].focus(); }
      }
    }

    note.addEventListener("input", () => { confirm.disabled = !note.value.trim(); });
    cancel.addEventListener("click", () => close(false));
    backdrop.addEventListener("click", () => close(false));
    confirm.addEventListener("click", async () => {
      confirm.disabled = true;
      error.hidden = true;
      try {
        await save(note.value.trim());
        close(true);
      } catch (problem) {
        error.textContent = problem.fields?.note ? `${problem.message} (${problem.fields.note})` : problem.message;
        error.hidden = false;
        confirm.disabled = !note.value.trim();
      }
    });
    document.addEventListener("keydown", onKey, true);
    document.body.append(backdrop, dialog);
    note.focus();
  });
}
