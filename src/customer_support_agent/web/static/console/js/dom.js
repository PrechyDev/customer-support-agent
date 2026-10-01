// Building the page safely. h() turns strings into TEXT nodes, so nothing from the API can ever become HTML
// (transcripts, summaries and reasons contain caller words; SPECS §8). There is no innerHTML anywhere.

export function h(tag, attrs = {}, ...children) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") element.className = value;
    else if (key === "dataset") Object.assign(element.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") element.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === "value") element.value = value;
    else element.setAttribute(key, value === true ? "" : String(value));
  }
  append(element, children);
  return element;
}

export function append(parent, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    parent.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return parent;
}

export function clear(element) {
  element.replaceChildren();
  return element;
}

// Fixed 24x24 stroke icons (handoff: 1.75 stroke, round caps). Shapes are constants, never data.
const ICONS = {
  menu: ["M4 7h16M4 12h16M4 17h16"],
  close: ["M6 6l12 12M18 6L6 18"],
  expand: ["M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7"],
  collapse: ["M20 10h-6V4M4 14h6v6M14 10l7-7M10 14l-7 7"],
  calendar: ["M3 10h18M8 3v4M16 3v4", "M5 5h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z"],
  chevronDown: ["M6 9l6 6 6-6"],
  chevronLeft: ["M15 6l-6 6 6 6"],
  chevronRight: ["M9 6l6 6-6 6"],
  sound: ["M11 5L6 9H3v6h3l5 4V5z", "M15.5 8.5a5 5 0 0 1 0 7"],
  soundOff: ["M11 5L6 9H3v6h3l5 4V5z", "M16 9l5 6M21 9l-5 6"],
};

export function icon(name, size = 16) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  for (const [k, v] of Object.entries({ width: size, height: size, viewBox: "0 0 24 24", fill: "none",
    stroke: "currentColor", "stroke-width": "1.75", "stroke-linecap": "round", "stroke-linejoin": "round",
    "aria-hidden": "true" })) svg.setAttribute(k, v);
  for (const d of ICONS[name]) {
    const path = document.createElementNS(ns, "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}

export function badge(text, tone = "grey") {
  return h("span", { class: `badge ${tone}` }, text);
}

export function initials(name) {
  return (name || "?").split(/\s+/).filter(Boolean).map((part) => part[0]).join("").slice(0, 2).toUpperCase();
}

let toastTimer = null;
export function toast(message) {
  document.querySelector(".toast")?.remove();
  clearTimeout(toastTimer);
  const box = h("div", { class: "toast", role: "status" }, message);
  document.body.append(box);
  toastTimer = setTimeout(() => box.remove(), 3500);
}

export function emptyRow(text) {
  return h("div", { class: "empty" }, text);
}

export function debounce(fn, ms) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}
