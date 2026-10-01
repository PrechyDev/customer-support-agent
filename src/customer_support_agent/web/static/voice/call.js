// The only file that talks to Vapi. Turns Vapi's events into a few plain callbacks.

const SDK_URL = "https://cdn.jsdelivr.net/npm/@vapi-ai/web@2.7.1/+esm"; // pinned
const log = (...args) => console.info("[voice]", ...args);

export class CallError extends Error {
  constructor(kind, detail) {
    super(detail || kind);
    this.kind = kind; // "mic" | "connect"
  }
}

let vapiPromise = null; // one Vapi client per page, created on the first call

async function config() {
  const response = await fetch("/voice/config", { headers: { Accept: "application/json" } });
  if (!response.ok) throw new CallError("connect", `voice config ${response.status}`);
  return response.json();
}

async function client(publicKey) {
  const module = await import(SDK_URL);
  // The +esm build wraps the CommonJS export: the class is on .default (sometimes .default.default).
  const Vapi = module.default?.default ?? module.default ?? module;
  return new Vapi(publicKey);
}

// Ask for the mic ourselves first, so a refusal is told apart from a connection problem.
async function checkMicrophone() {
  if (!navigator.mediaDevices?.getUserMedia) throw new CallError("mic", "no mediaDevices (needs https or localhost)");
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach((track) => track.stop());
  } catch (error) {
    throw new CallError("mic", error?.name || "getUserMedia failed");
  }
}

export function createCall(handlers) {
  let vapi = null;
  let assistantId = null;
  let attempt = 0; // a Cancel or a new call makes older start() results stale
  let inCall = false; // from start() until Vapi says the call ended

  function listen(instance) {
    instance.on("call-start", () => handlers.onLive());
    instance.on("speech-start", () => handlers.onSpeaking(true));
    instance.on("speech-end", () => handlers.onSpeaking(false));
    instance.on("call-end", () => {
      inCall = false;
      handlers.onEnded();
    });
    instance.on("message", (message) => {
      if (typeof message?.type === "string" && message.type.startsWith("transcript") && message.transcript) {
        handlers.onTranscript(message.role === "user" ? "user" : "assistant", message.transcript,
          message.transcriptType === "final");
      }
    });
    instance.on("error", (error) => {
      log("Vapi error", error);
      handlers.onError(new CallError("connect", "vapi error"));
    });
  }

  async function ensureClient() {
    if (!vapiPromise) {
      vapiPromise = config().then(async (settings) => {
        assistantId = settings.assistantId;
        const instance = await client(settings.publicKey);
        listen(instance);
        return instance;
      });
      vapiPromise.catch(() => { vapiPromise = null; }); // allow Try again
    }
    vapi = await vapiPromise;
  }

  return {
    // Loads the SDK ahead of the first call; a failure here is retried by start().
    prepare() {
      ensureClient().catch((error) => log("voice not ready yet", error?.message));
    },

    // caller: the form values; greetingName: first name for Vapi's first message
    // onDialing: called once the mic is allowed, while Vapi connects (the page starts the ringing tone)
    async start(caller, greetingName, onDialing = () => {}) {
      const mine = ++attempt;
      await checkMicrophone();
      if (mine !== attempt) return null; // cancelled during the mic prompt
      onDialing();
      try {
        await ensureClient();
      } catch (error) {
        throw error instanceof CallError ? error : new CallError("connect", "could not load voice");
      }
      if (mine !== attempt) return null; // cancelled while loading
      const metadata = { name: caller.name, email: caller.email };
      if (caller.company) metadata.company = caller.company;
      if (caller.phone) metadata.phone = caller.phone;
      const overrides = { metadata };
      if (greetingName) overrides.variableValues = { name: greetingName };
      let call;
      inCall = true;
      try {
        call = await vapi.start(assistantId, overrides);
      } catch (error) {
        inCall = false;
        log("start failed", error);
        throw new CallError("connect", "start failed");
      }
      if (mine !== attempt) { // cancelled while connecting: the call joined anyway, so leave it
        vapi.stop();
        inCall = false;
        return null;
      }
      if (!call) {
        inCall = false;
        throw new CallError("connect", "start returned no call");
      }
      log("call started", call.id);
      return call.id || null;
    },

    stop() {
      attempt += 1;
      if (vapi && inCall) vapi.stop();
      inCall = false;
    },

    setMuted(muted) {
      if (vapi) vapi.setMuted(muted);
    },
  };
}
