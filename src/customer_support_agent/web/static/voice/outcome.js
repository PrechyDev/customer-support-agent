// After the call: the outcome box from our own records, and the "Did this help?" rating (FRONTEND_PLAN §4.5).
// Never "booked" and never a timeline (SPECS §6).

const RETRY_DELAYS_MS = [0, 1500, 1500, 2000]; // records are written in the background: ~5 s in all
const log = (...args) => console.info("[voice]", ...args);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export async function fetchOutcome(callId) {
  for (const delay of RETRY_DELAYS_MS) {
    await sleep(delay);
    try {
      const response = await fetch(`/voice/calls/${encodeURIComponent(callId)}/outcome`);
      if (response.ok) return await response.json();
      log("outcome not ready", response.status);
    } catch (error) {
      log("outcome request failed", error?.name);
    }
  }
  return null;
}

// Our record -> { tone, title, reference, detail }
export function describe(outcome) {
  switch (outcome?.outcome) {
    case "callback":
      return {
        tone: "esc", title: "Callback requested", reference: outcome.reference,
        detail: outcome.callback
          ? `A specialist will call you on ${outcome.callback}.`
          : "A specialist will call you as soon as one is free.",
      };
    case "email":
      return {
        tone: "esc", title: "Passed to a specialist", reference: outcome.reference,
        detail: outcome.email_masked
          ? `A specialist will email you at ${outcome.email_masked}.`
          : "A specialist will follow up by email.",
      };
    case "ticket":
      return { tone: "esc", title: "Ticket created", reference: outcome.reference, detail: "Our team will look into it." };
    case "none":
      return {
        tone: "ok", title: "Thanks for calling", reference: null,
        detail: "If anything else comes up, you can reach us through your RelayPay dashboard.",
      };
    default:
      return null;
  }
}

export async function sendRating(callId, helpful) {
  try {
    const response = await fetch(`/voice/calls/${encodeURIComponent(callId)}/rating`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ helpful }),
    });
    if (!response.ok) log("rating not saved", response.status);
  } catch (error) {
    log("rating request failed", error?.name);
  }
}
