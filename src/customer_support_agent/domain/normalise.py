"""Turn what callers say (through speech-to-text) into exact values the database can match.

Spoken input is messy: "amara at lagos ledger dot example", "T X N nine zero zero one".
"""

import re

_DIGIT_WORDS = {
    "zero": "0", "oh": "0", "o": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}
_EMAIL = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$")
REFERENCE = re.compile(r"^(TXN|PAY)-\d{4}$")


def normalise_email(raw: str | None) -> str | None:
    """'Amara at Lagos Ledger dot example' -> 'amara@lagosledger.example'. None if it isn't an email."""
    if not raw:
        return None
    text = f" {raw.strip().lower()} "
    text = re.sub(r"\s+at\s+", "@", text)
    text = re.sub(r"\s+dot\s+", ".", text)
    text = re.sub(r"\s+", "", text)
    return text if _EMAIL.match(text) else None


def normalise_company(raw: str | None) -> str:
    """'Lagos Ledger' / 'lagos-ledger' / 'LagosLedger' -> 'lagosledger', for comparison only."""
    return re.sub(r"[^a-z0-9]", "", (raw or "").lower())


def parse_reference(raw: str | None, default_prefix: str = "TXN") -> str | None:
    """'T X N nine zero zero one', 'txn 9001', 'payout 7002' -> 'TXN-9001' / 'PAY-7002'. None if unclear."""
    if not raw:
        return None
    words = re.findall(r"[a-z]+|\d", raw.lower())
    digits = "".join(_DIGIT_WORDS.get(w, w) for w in words if w.isdigit() or w in _DIGIT_WORDS)
    letters = "".join(w for w in words if not w.isdigit() and w not in _DIGIT_WORDS)
    if len(digits) != 4:
        return None
    if "pay" in letters:
        prefix = "PAY"
    elif "txn" in letters or "transaction" in letters or "tx" in letters:
        prefix = "TXN"
    else:
        prefix = default_prefix
    return f"{prefix}-{digits}"


def mask_email(email: str | None) -> str:
    """For logs: 'amara@lagosledger.example' -> 'a***@lagosledger.example'."""
    if not email or "@" not in email:
        return "(none)"
    local, domain = email.split("@", 1)
    return f"{local[:1]}***@{domain}"
