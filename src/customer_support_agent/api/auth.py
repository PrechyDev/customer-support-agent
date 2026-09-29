"""Checks the secret Vapi sends with every Custom LLM request (SPECS §8)."""

import hmac


def check_vapi_secret(header: str | None, secret: str) -> str | None:
    """Returns the format that matched ("bearer" or "raw"), or None if the secret is wrong or missing.

    Vapi's docs don't say whether it sends "Bearer <secret>" or the bare secret, so both are
    accepted; the matched format is logged (never the value) so we can tighten this later.
    Comparisons are constant-time so timing can't reveal the secret.
    """
    if not header:
        return None
    provided = header.encode()
    if hmac.compare_digest(provided, f"Bearer {secret}".encode()):
        return "bearer"
    if hmac.compare_digest(provided, secret.encode()):
        return "raw"
    return None
