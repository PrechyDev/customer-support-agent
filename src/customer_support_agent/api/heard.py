"""What the caller actually heard of the agent's last reply (SPECS §2b).

When the caller interrupts after our whole reply was sent, the agent remembers all of it, but the
caller only heard the start. Vapi records the assistant's message cut off where it was interrupted,
so comparing that with what we sent tells us what was missed, and a note tells the agent.
"""

import re

_MIN_MISSED_CHARS = 10  # smaller differences are just Vapi's punctuation, not a real cut-off


def _normalise(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split())


def heard_note(sent: str | None, heard: str | None) -> str | None:
    """A note for the agent if the caller heard only the start of what we sent, else None."""
    if not sent or not heard:
        return None
    said, got = _normalise(sent), _normalise(heard)
    if not got or not said.startswith(got) or len(said) - len(got) < _MIN_MISSED_CHARS:
        return None
    heard_text = heard.replace("●", "").strip()  # Vapi marks the cut with "●"
    return f'[System note: your last reply was cut off. The customer only heard: "{heard_text}"]'
