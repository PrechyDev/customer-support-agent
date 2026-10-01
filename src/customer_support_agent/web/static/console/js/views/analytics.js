// Analytics: date range (presets + calendar, applied only on Apply), KPIs, conversations over time, how they ended,
// and the questions the assistant couldn't answer. Dates are calendar days (UTC, as the backend counts them).

import { api, query } from "../api.js";
import { badge, emptyRow, h, icon } from "../dom.js";
import { OUTCOMES, duration, pct } from "../format.js";

const DAY_MS = 86400000;
const MAX_DAYS = 366;
const label = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
const monthLabel = new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric", timeZone: "UTC" });
const short = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", timeZone: "UTC" });

const iso = (d) => d.toISOString().slice(0, 10);
const utcDay = (text) => new Date(`${text}T00:00:00Z`);
const addDays = (d, n) => new Date(d.getTime() + n * DAY_MS);
const today = () => utcDay(new Date().toISOString().slice(0, 10));

function presets() {
  const t = today();
  const first = new Date(Date.UTC(t.getUTCFullYear(), t.getUTCMonth(), 1));
  const lastMonthEnd = addDays(first, -1);
  return [
    ["Today", t, t], ["Last 7 days", addDays(t, -6), t], ["Last 28 days", addDays(t, -27), t],
    ["Last 90 days", addDays(t, -89), t], ["This month", first, t],
    ["Last month", new Date(Date.UTC(lastMonthEnd.getUTCFullYear(), lastMonthEnd.getUTCMonth(), 1)), lastMonthEnd],
  ];
}

function rangeText(from, to) {
  return iso(from) === iso(to) ? label.format(from) : `${label.format(from)} – ${label.format(to)}`;
}

export async function render(container, params, ctx) {
  const initial = presets()[1];
  let applied = { name: initial[0], from: initial[1], to: initial[2] };
  const button = h("button", { type: "button", class: "range-button", "aria-haspopup": "dialog", "aria-expanded": "false" });
  const wrap = h("div", { class: "range-wrap" }, button);
  const results = h("div", { style: "display:flex;flex-direction:column;gap:20px" });
  container.replaceChildren(h("div", { class: "page" }, wrap, results));
  let popover = null;

  function drawButton() {
    button.replaceChildren(icon("calendar"), h("span", { class: "strong" }, applied.name),
      h("span", { class: "muted" }, rangeText(applied.from, applied.to)), icon("chevronDown", 14));
  }

  function closePicker() {
    popover?.remove();
    popover = null;
    button.setAttribute("aria-expanded", "false");
    document.removeEventListener("mousedown", outside);
  }

  function outside(event) {
    if (popover && !wrap.contains(event.target)) closePicker();
  }

  function openPicker() {
    if (popover) return closePicker();
    let draft = { ...applied };
    let picking = null; // first click of a custom range
    let month = new Date(Date.UTC(applied.to.getUTCFullYear(), applied.to.getUTCMonth(), 1));
    const presetList = h("div", { class: "presets" });
    const calendar = h("div", { class: "calendar" });
    const summary = h("span", {});
    const apply = h("button", { type: "button", class: "btn btn-primary btn-sm" }, "Apply");
    const cancel = h("button", { type: "button", class: "btn btn-secondary btn-sm", onclick: closePicker }, "Cancel");
    popover = h("div", { class: "popover", role: "dialog", "aria-label": "Choose dates" },
      h("div", { class: "popover-body" }, presetList, calendar),
      h("div", { class: "popover-foot" }, summary, h("div", { class: "row" }, cancel, apply)));

    function drawPicker() {
      presetList.replaceChildren(...[...presets(), ["Custom", null, null]].map(([name, from, to]) => h("button", {
        type: "button", class: "preset", "aria-pressed": String(draft.name === name),
        onclick: () => {
          if (from) { draft = { name, from, to }; month = new Date(Date.UTC(to.getUTCFullYear(), to.getUTCMonth(), 1)); }
          else draft = { ...draft, name: "Custom" };
          picking = null;
          drawPicker();
        } }, name)));
      const t = today();
      const firstWeekday = (month.getUTCDay() + 6) % 7; // Monday first
      const days = new Date(Date.UTC(month.getUTCFullYear(), month.getUTCMonth() + 1, 0)).getUTCDate();
      const cells = [];
      for (let i = 0; i < firstWeekday; i += 1) cells.push(h("span"));
      for (let d = 1; d <= days; d += 1) {
        const date = new Date(Date.UTC(month.getUTCFullYear(), month.getUTCMonth(), d));
        const from = picking || draft.from;
        const to = picking ? picking : draft.to;
        const edge = iso(date) === iso(from) || iso(date) === iso(to);
        const inside = date > from && date < to;
        cells.push(h("button", { type: "button", class: `cal-day ${edge ? "edge" : inside ? "in-range" : ""}`,
          disabled: date > t, "aria-label": label.format(date), "aria-pressed": String(edge),
          onclick: () => {
            if (!picking) { picking = date; draft = { name: "Custom", from: date, to: date }; }
            else {
              const [a, b] = date < picking ? [date, picking] : [picking, date];
              draft = { name: "Custom", from: a, to: b };
              picking = null;
            }
            drawPicker();
          } }, String(d)));
      }
      const nextMonth = new Date(Date.UTC(month.getUTCFullYear(), month.getUTCMonth() + 1, 1));
      calendar.replaceChildren(
        h("div", { class: "cal-head" },
          h("button", { type: "button", class: "icon-button", "aria-label": "Previous month", onclick: () => {
            month = new Date(Date.UTC(month.getUTCFullYear(), month.getUTCMonth() - 1, 1)); drawPicker(); } }, icon("chevronLeft", 14)),
          h("span", {}, monthLabel.format(month)),
          h("button", { type: "button", class: "icon-button", "aria-label": "Next month", disabled: nextMonth > t, onclick: () => {
            month = nextMonth; drawPicker(); } }, icon("chevronRight", 14))),
        h("div", { class: "cal-grid" }, ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"].map((d) => h("span", { class: "cal-dow" }, d)), cells));
      const span = Math.round((draft.to - draft.from) / DAY_MS) + 1;
      summary.textContent = picking ? "Choose the end date" : `${rangeText(draft.from, draft.to)} (${span} day${span === 1 ? "" : "s"})`;
      apply.disabled = Boolean(picking) || span > MAX_DAYS;
      if (span > MAX_DAYS) summary.textContent = `Pick a range of up to ${MAX_DAYS} days.`;
    }

    apply.addEventListener("click", () => {
      applied = draft;
      closePicker();
      drawButton();
      load();
    });
    drawPicker();
    wrap.append(popover);
    button.setAttribute("aria-expanded", "true");
    setTimeout(() => document.addEventListener("mousedown", outside));
  }

  button.addEventListener("click", openPicker);
  wrap.addEventListener("keydown", (event) => { if (event.key === "Escape" && popover) { closePicker(); button.focus(); } });

  async function load() {
    results.replaceChildren(h("p", { class: "muted" }, "Loading…"));
    const data = await api(`/analytics${query({ from: iso(applied.from), to: iso(applied.to) })}`);
    const k = data.kpis;
    const change = k.conversations_change_pct;
    const max = Math.max(1, ...data.series.points.map((p) => p.count));
    const bucketName = { day: "day", week: "week", month: "month" }[data.series.bucket];
    const lastPoint = data.series.points[data.series.points.length - 1];
    const totalEnded = Object.values(data.ended).reduce((a, b) => a + b, 0);
    const kpi = (labelText, value, note, noteClass = "") => h("div", { class: "kpi" }, h("span", { class: "label" }, labelText),
      h("span", { class: "value", style: "font-size:26px" }, value), h("span", { class: `note ${noteClass}` }, note || " "));
    results.replaceChildren(
      h("div", { class: "kpis", style: "grid-template-columns:repeat(auto-fit,minmax(180px,1fr))" },
        kpi("Conversations", String(k.conversations),
          applied.name === "Today" ? "Day in progress" : change === null ? "No earlier data to compare" : `${change > 0 ? "+" : ""}${change}% vs previous period`,
          change > 0 ? "delta-up" : change < 0 ? "delta-down" : ""),
        kpi("Answered by assistant", pct(k.answered_by_assistant_pct)),
        kpi("Handed to a specialist", pct(k.handed_to_specialist_pct)),
        kpi("Rated helpful", pct(k.rated_helpful_pct), k.rated_helpful_pct === null ? "No ratings yet" : "of rated calls"),
        kpi("Average conversation", k.average_duration_s === null ? "–" : duration(k.average_duration_s))),
      h("div", { class: "dash-grid", style: "grid-template-columns:repeat(auto-fit,minmax(min(100%,380px),1fr))" },
        h("section", { class: "card" }, h("div", { class: "card-head" }, h("span", { class: "card-title" }, `Conversations per ${bucketName}`)),
          h("div", { class: "chart", role: "img", "aria-label": data.series.points.map((p) => `${p.start}: ${p.count}`).join(", ") },
            data.series.points.map((p) => h("div", { class: "bar-col" }, h("span", { class: "v" }, String(p.count)),
              h("div", { class: "bar", style: `height:${Math.round((p.count / max) * 150)}px${p === lastPoint && iso(applied.to) === iso(today()) ? ";opacity:0.6" : ""}` }),
              h("span", { class: "l" }, short.format(utcDay(p.start))))))),
        h("section", { class: "card" }, h("div", { class: "card-head" }, h("span", { class: "card-title" }, "How conversations ended")),
          h("div", { class: "hbars" }, Object.entries(OUTCOMES).map(([key, [name, tone]]) => {
            const n = data.ended[key] || 0;
            const share = totalEnded ? Math.round((100 * n) / totalEnded) : 0;
            return h("div", { class: "hbar" }, h("span", {}, name),
              h("div", { class: "track" }, h("div", { class: `fill ${tone}`, style: `width:${share}%` })),
              h("span", { class: "n" }, `${n} · ${share}%`));
          }), h("p", { class: "small muted", style: "margin:4px 0 0;line-height:1.5" },
            "Each call is counted once, by its biggest outcome. Handovers to a specialist include their ticket.")))),
      h("section", { class: "card" },
        h("div", { class: "card-head", style: "flex-direction:column;align-items:flex-start;gap:2px" },
          h("span", { class: "card-title" }, "Questions the assistant couldn't answer"),
          h("span", { class: "card-sub" }, "Not covered by the knowledge base. Adding them reduces handoffs.")),
        data.unanswered.length ? data.unanswered.map((q) => h("div", { class: "list-row" },
          h("span", { style: "font-size:14px" }, q.question),
          badge(q.times === 1 ? "Asked once" : `Asked ${q.times} times`))) : emptyRow("None in this period.")));
  }

  drawButton();
  await load();
  return { destroy: closePicker };
}
