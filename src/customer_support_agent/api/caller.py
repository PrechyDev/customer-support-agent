"""The pre-call form (name, email, optional company), as Vapi passes it along with each request.

The voice page sends it as call metadata. Depending on the Vapi setting it arrives at the top of the
request (metadataSendMode "variable"), or inside the call or assistant. It's typed by the caller, so it's
cleaned and capped here: it's contact information only, never proof of identity (SPECS §3).
"""

import re
from typing import Any

from customer_support_agent.domain.normalise import normalise_email

MAX_NAME = 80
MAX_COMPANY = 100
_UNSAFE = re.compile(r"[^\w .,'&-]")  # no tags, brackets or line breaks can reach the prompt


def _metadata_blocks(body: dict) -> list[Any]:
    call = body.get("call") if isinstance(body.get("call"), dict) else {}
    assistant = body.get("assistant") if isinstance(body.get("assistant"), dict) else {}
    overrides = call.get("assistantOverrides") if isinstance(call.get("assistantOverrides"), dict) else {}
    return [body.get("metadata"), overrides.get("metadata"), call.get("metadata"), assistant.get("metadata")]


def _clean(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(_UNSAFE.sub(" ", value).split())[:limit].strip()
    return text or None


def caller_from_vapi(body: Any) -> dict[str, str] | None:
    """The first metadata block with any usable field, cleaned. None if there's no form data."""
    if not isinstance(body, dict):
        return None
    for block in _metadata_blocks(body):
        if not isinstance(block, dict):
            continue
        email = block.get("email")
        caller = {
            "name": _clean(block.get("name"), MAX_NAME),
            "email": normalise_email(email) if isinstance(email, str) else None,
            "company": _clean(block.get("company"), MAX_COMPANY),
        }
        caller = {k: v for k, v in caller.items() if v}
        if caller:
            return caller
    return None
