"""What Bex last said on each call, so a tool can tell whether the caller already heard a value read back.

Bex sometimes reads a phone number or email back herself before calling the tool. Without this, the tool
then read it back a second time (seen in voice tests). With it, the tool accepts a confirmation only when the
exact value it will store was in what the caller just heard. One process serves all calls (Cloud Run
max-instances 1), so an in-memory map is enough; entries are dropped when the call ends.
"""

import re

_last: dict[str, str] = {}


def remember(conversation_id: str, text: str) -> None:
    if text:
        _last[conversation_id] = text


def forget(conversation_id: str) -> None:
    _last.pop(conversation_id, None)


def last_said(conversation_id: str) -> str:
    return _last.get(conversation_id, "")


def heard_digits(conversation_id: str, digits: str) -> bool:
    """True if this exact digit sequence was in Bex's last words (spaces, dashes and dots ignored)."""
    return bool(digits) and digits in re.sub(r"\D", "", last_said(conversation_id))


def heard_text(conversation_id: str, *forms: str) -> bool:
    """True if any of these spellings (e.g. 'ada@x.com', 'ada at x dot com') was in Bex's last words."""
    said = " ".join(last_said(conversation_id).lower().split())
    return any(form and " ".join(form.lower().split()) in said for form in forms)
