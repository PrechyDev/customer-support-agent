// Live captions. Text goes in with textContent only: it's the caller's own words.

const LABELS = { user: "You", assistant: "RelayPay" };
const NEAR_BOTTOM_PX = 24;

export function createCaptions(list, announcer) {
  const inProgress = { user: null, assistant: null }; // one greyed row per speaker while they talk
  let followBottom = true;

  list.addEventListener("scroll", () => {
    followBottom = list.scrollHeight - list.scrollTop - list.clientHeight < NEAR_BOTTOM_PX;
  });

  function newRow(role) {
    const row = document.createElement("div");
    row.className = "line";
    row.dataset.role = role;
    const who = document.createElement("div");
    who.className = "who";
    who.textContent = LABELS[role];
    const text = document.createElement("div");
    text.className = "text";
    row.append(who, text);
    list.append(row);
    return row;
  }

  function scroll() {
    if (followBottom) list.scrollTop = list.scrollHeight;
  }

  return {
    add(role, text, isFinal) {
      const row = inProgress[role] || newRow(role);
      row.querySelector(".text").textContent = text;
      row.dataset.partial = isFinal ? "false" : "true";
      inProgress[role] = isFinal ? null : row;
      if (isFinal) announcer.textContent = `${LABELS[role]}: ${text}`;
      scroll();
    },

    // The call ended mid-sentence: keep what was caught, as plain text.
    settle() {
      for (const role of Object.keys(inProgress)) {
        if (inProgress[role]) inProgress[role].dataset.partial = "false";
        inProgress[role] = null;
      }
    },

    clear() {
      list.replaceChildren();
      announcer.textContent = "";
      inProgress.user = inProgress.assistant = null;
      followBottom = true;
    },

    get isEmpty() {
      return list.childElementCount === 0;
    },
  };
}
