// A soft ringing tone while the call connects (UK/Nigeria style: 400 + 450 Hz, ring-ring, pause).
// Made with the Web Audio API, so there's no audio file. The AudioContext must be created during the
// Start call click (browsers only allow sound after a user gesture).

const FREQUENCIES = [400, 450];
const VOLUME = 0.06;
const PATTERN = [[0, 0.4], [0.6, 1.0]]; // seconds within each cycle when the tone is on
const CYCLE_SECONDS = 3;
const MAX_RING_SECONDS = 30; // a safety stop: never ring forever

export function createRingtone() {
  let context = null;
  let gain = null;
  let oscillators = [];
  let timer = null;
  let stopAt = 0;

  function schedule(from) {
    for (const [on, off] of PATTERN) {
      gain.gain.setValueAtTime(VOLUME, from + on);
      gain.gain.setValueAtTime(0, from + off);
    }
  }

  return {
    // Call inside the click handler.
    unlock() {
      if (context) return;
      try {
        context = new AudioContext();
      } catch (error) {
        console.info("[voice] no ringing tone:", error?.name);
      }
    },

    start() {
      if (!context || timer) return;
      context.resume();
      gain = context.createGain();
      gain.gain.value = 0;
      gain.connect(context.destination);
      for (const frequency of FREQUENCIES) {
        const oscillator = context.createOscillator();
        oscillator.frequency.value = frequency;
        oscillator.connect(gain);
        oscillator.start();
        oscillators.push(oscillator);
      }
      let next = context.currentTime + 0.05;
      stopAt = next + MAX_RING_SECONDS;
      schedule(next);
      schedule(next + CYCLE_SECONDS); // always one cycle ahead, so a late timer can't stutter
      timer = setInterval(() => {
        next += CYCLE_SECONDS;
        if (next >= stopAt) return this.stop();
        schedule(next + CYCLE_SECONDS);
      }, CYCLE_SECONDS * 1000);
    },

    stop() {
      clearInterval(timer);
      timer = null;
      oscillators.forEach((oscillator) => oscillator.stop());
      oscillators = [];
      if (gain) {
        gain.disconnect();
        gain = null;
      }
    },

    get ringing() {
      return timer !== null;
    },
  };
}
