// Voice page state machine (FRONTEND_PLAN §3, §4). Two screens:
//   details (idle)  ->  call: connecting (ringing) -> live -> ended, or error
// One state object; render() draws the page from it.

import { createCall } from "./call.js";
import { createCaptions } from "./captions.js";
import { firstName, watchForm } from "./form.js";
import { describe, fetchOutcome, sendRating } from "./outcome.js";
import { createRingtone } from "./ringtone.js";

const $ = (id) => document.getElementById(id);
const log = (...args) => console.info("[voice]", ...args);

const ERRORS = {
  mic: ["Microphone unavailable", "We could not access your microphone",
    "Allow microphone access in your browser settings and try again."],
  connect: ["Call could not connect", "Please check your connection",
    "Something went wrong while connecting the call. Please try again."],
};
const CONNECT_TIMEOUT_MS = 20000; // from the mic being allowed: longer means something went wrong
const RATED = { true: "Thanks for your feedback.", false: "Thanks. We will use this to improve." };

const state = {
  status: "idle",        // idle (details screen) | connecting | live | ended | error
  dialing: false,        // connecting: the mic is allowed and the tone is ringing
  phase: "listening",    // live only: listening | speaking | waiting ("One moment")
  muted: false,
  elapsed: 0,
  errorKind: "mic",
  callId: null,
  values: null,
  transcriptOpen: true,
};
let timer = null;
let connectTimer = null;

const card = $("card");
const ringtone = createRingtone();
const captions = createCaptions($("transcript-lines"), $("caption-announcer"));
const call = createCall({ onLive, onSpeaking, onTranscript, onEnded, onError });
const form = watchForm($("caller-form"), (valid, values) => {
  state.values = values;
});

function setText(element, text) {
  if (element.textContent !== text) element.textContent = text; // don't re-announce live regions
}

const clock = (seconds) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

function statusLines() {
  switch (state.status) {
    case "connecting":
      return ["Calling RelayPay", state.dialing ? "Connecting you to support" : "Allow the microphone if your browser asks"];
    case "live": {
      const label = state.muted ? "You are muted"
        : state.phase === "speaking" ? "RelayPay is speaking"
        : state.phase === "waiting" ? "One moment" : "Listening";
      return [label, clock(state.elapsed)];
    }
    case "error":
      return ERRORS[state.errorKind].slice(0, 2);
    default:
      return ["", ""];
  }
}

function render() {
  const { status } = state;
  const screen = status === "idle" ? "details" : "call";
  card.dataset.state = status;
  card.dataset.phase = state.phase;
  card.dataset.muted = String(state.muted);

  for (const element of card.querySelectorAll("[data-screen]")) element.hidden = element.dataset.screen !== screen;
  for (const element of card.querySelectorAll("[data-for]")) element.hidden = element.dataset.for !== status;
  $("call-area").hidden = status === "ended";

  if (state.values) setText($("caller-summary-text"), `Calling as ${state.values.name} · ${state.values.email}`);
  $("edit-details").hidden = status !== "ended" && status !== "error";

  const [label, sub] = statusLines();
  setText($("status-label"), label);
  setText($("status-sub"), sub);
  setText($("error-copy"), ERRORS[state.errorKind][2]);
  $("mute").setAttribute("aria-pressed", String(state.muted));
  setText($("mute-label"), state.muted ? "Unmute" : "Mute");

  $("transcript").hidden = !(status === "live" || status === "ended") || captions.isEmpty;
  $("transcript-lines").hidden = !state.transcriptOpen;
  setText($("toggle-transcript"), state.transcriptOpen ? "Hide" : "Show");
  $("toggle-transcript").setAttribute("aria-expanded", String(state.transcriptOpen));
}

function set(changes) {
  Object.assign(state, changes);
  render();
}

function stopTimer() {
  clearInterval(timer);
  timer = null;
  clearTimeout(connectTimer);
  connectTimer = null;
}

// --- Vapi events -------------------------------------------------------------------------
function onLive() {
  if (state.status !== "connecting") return;
  ringtone.stop(); // picked up
  set({ status: "live", phase: "listening", elapsed: 0 });
  stopTimer();
  timer = setInterval(() => set({ elapsed: state.elapsed + 1 }), 1000);
  $("end-call").focus();
  log("live");
}

function onSpeaking(speaking) {
  if (state.status === "live") set({ phase: speaking ? "speaking" : "listening" });
}

function onTranscript(role, text, isFinal) {
  if (state.status !== "live") return;
  captions.add(role, text, isFinal);
  // From the caller's last words until RelayPay starts speaking: "One moment"
  if (role === "user" && state.phase !== "speaking") state.phase = isFinal ? "waiting" : "listening";
  render();
}

function onEnded() {
  if (state.status === "live") finish();
  else if (state.status === "connecting") showError("connect");
}

function onError(error) {
  if (state.status === "connecting") showError(error.kind);
  // While live, Vapi follows a fatal error with call-end, which ends the call here.
}

// --- Actions -----------------------------------------------------------------------------
function showError(kind) {
  ringtone.stop();
  stopTimer();
  log("error", kind);
  set({ status: "error", errorKind: kind === "mic" ? "mic" : "connect" });
  $("try-again").focus();
}

async function startCall() {
  const values = { ...state.values };
  captions.clear();
  set({ status: "connecting", dialing: false, muted: false, elapsed: 0, callId: null, phase: "listening" });
  $("cancel-call").focus();
  try {
    const callId = await call.start(values, firstName(values.name), () => {
      if (state.status !== "connecting") return;
      set({ dialing: true });
      ringtone.start();
      connectTimer = setTimeout(() => {
        if (state.status !== "connecting") return;
        log("connect timed out");
        call.stop(); // hang up the half-started call so it can't connect later
        showError("connect");
      }, CONNECT_TIMEOUT_MS);
    });
    if (state.status === "connecting" || state.status === "live") state.callId = callId;
  } catch (error) {
    if (state.status === "connecting") showError(error.kind);
  }
}

function finish() {
  ringtone.stop();
  stopTimer();
  captions.settle();
  set({ status: "ended" });
  resetEnded();
  $("new-conversation").focus();
  showOutcome(state.callId);
  log("ended", state.callId);
}

function resetEnded() {
  $("outcome").hidden = true;
  $("rating").hidden = !state.callId;
  $("rating").dataset.rated = "false";
  $("rating-buttons").hidden = false;
  setText($("rating-question"), "Did this help?");
}

async function showOutcome(callId) {
  if (!callId) return;
  const box = describe(await fetchOutcome(callId));
  if (!box || state.callId !== callId || state.status !== "ended") return; // a new conversation started meanwhile
  const outcome = $("outcome");
  outcome.dataset.tone = box.tone;
  setText($("outcome-title"), box.title);
  setText($("outcome-detail"), box.detail);
  $("outcome-ref").hidden = !box.reference;
  setText($("outcome-ref-value"), box.reference || "");
  outcome.hidden = false;
}

function backToDetails(focusId = "start-call") {
  ringtone.stop();
  call.stop();
  stopTimer();
  captions.clear();
  set({ status: "idle", callId: null, muted: false, elapsed: 0, dialing: false });
  form.refresh();
  $(focusId).focus();
}

$("caller-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (state.status !== "idle") return;
  ringtone.unlock(); // sound is only allowed from a click
  const wrong = form.revealAll();
  if (wrong) {
    wrong.focus();
    return;
  }
  startCall();
});
$("cancel-call").addEventListener("click", () => backToDetails());
$("try-again").addEventListener("click", () => {
  ringtone.unlock();
  startCall();
});
$("back-to-details").addEventListener("click", () => backToDetails());
$("end-call").addEventListener("click", () => {
  call.stop();
  if (state.status === "live") finish();
});
$("mute").addEventListener("click", () => {
  call.setMuted(!state.muted);
  set({ muted: !state.muted });
});
$("new-conversation").addEventListener("click", () => backToDetails());
$("edit-details").addEventListener("click", () => backToDetails("name"));
$("toggle-transcript").addEventListener("click", () => set({ transcriptOpen: !state.transcriptOpen }));
$("rating-buttons").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-helpful]");
  if (!button || !state.callId) return;
  const helpful = button.dataset.helpful === "true";
  $("rating-buttons").hidden = true;
  $("rating").dataset.rated = "true";
  setText($("rating-question"), RATED[helpful]);
  $("new-conversation").focus();
  sendRating(state.callId, helpful);
});
window.addEventListener("pagehide", () => {
  ringtone.stop();
  call.stop();
});

$("start-call").disabled = false; // the page is ready (the HTML starts with it disabled)
call.prepare(); // load the voice SDK in the background so Start call connects faster
render();
