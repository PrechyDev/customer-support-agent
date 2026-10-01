// New tickets and escalations (SPECS §6 "New ticket and escalation notifications"): poll every 30 s, a soft chime
// and a badge on Cases. Browsers block sound until a click, so there's an "Enable sound" button; the badge works
// without it. The last time checked is remembered, so a refresh doesn't ping again for old items.

import { api } from "./api.js";
import { h, icon } from "./dom.js";

const POLL_MS = 30000;
const SINCE_KEY = "relaypay.console.since";
const SOUND_KEY = "relaypay.console.sound";

function stored(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function store(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // private mode or storage blocked: the ping still works for this page view
  }
}

export function createPing({ soundSlot, onNew }) {
  let timer = null;
  let since = stored(SINCE_KEY);
  let unseen = 0;
  let audio = null;
  let choice = stored(SOUND_KEY); // "on", "off", or null (never chosen)

  // One toggle: "Enable sound" (never chosen, or the browser needs a click again after a reload),
  // "Sound on" (click to mute), "Sound off" (click to turn on). The choice is remembered.
  const button = h("button", { type: "button", class: "btn btn-secondary btn-xs", onclick: () => toggle() });
  soundSlot.replaceChildren(button);

  const soundOn = () => choice === "on" && Boolean(audio);

  function showButton() {
    const label = soundOn() ? "Sound on" : choice === "off" ? "Sound off" : "Enable sound";
    button.replaceChildren(icon(soundOn() ? "sound" : "soundOff", 14), label);
    button.setAttribute("aria-pressed", String(soundOn()));
    button.title = soundOn() ? "Chimes for new escalations and tickets. Click to mute." : "Turn on a chime for new escalations and tickets.";
  }

  function toggle() {
    if (soundOn()) {
      choice = "off";
    } else {
      try {
        audio = audio || new AudioContext(); // browsers allow sound only after a click
        audio.resume();
        choice = "on";
      } catch (error) {
        console.info("[console] sound unavailable", error?.name);
      }
    }
    store(SOUND_KEY, choice);
    showButton();
    chime(); // a short preview when it's turned on
  }

  function chime() {
    if (!soundOn()) return;
    const t = audio.currentTime;
    for (const [i, frequency] of [[0, 660], [1, 880]]) {
      const osc = audio.createOscillator();
      const gain = audio.createGain();
      osc.frequency.value = frequency;
      gain.gain.setValueAtTime(0, t + i * 0.18);
      gain.gain.linearRampToValueAtTime(0.08, t + i * 0.18 + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + i * 0.18 + 0.35);
      osc.connect(gain).connect(audio.destination);
      osc.start(t + i * 0.18);
      osc.stop(t + i * 0.18 + 0.4);
    }
  }

  async function check() {
    try {
      const data = await api(`/new${since ? `?since=${encodeURIComponent(since)}` : ""}`);
      const first = !since;
      since = data.now;
      store(SINCE_KEY, since);
      if (!first && data.count > 0) {
        unseen += data.count;
        chime();
        onNew(unseen);
      }
    } catch (error) {
      console.info("[console] new-item check failed", error?.code);
    }
  }

  return {
    start() {
      showButton();
      check();
      timer = setInterval(check, POLL_MS);
    },
    stop() {
      clearInterval(timer);
      timer = null;
    },
    seen() {
      unseen = 0;
    },
    check, // for tests: run a check now
  };
}
