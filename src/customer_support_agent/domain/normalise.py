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


# Countries where a local number starts with a 0 that's dropped after the country code ("0814..." -> "+234814...").
TRUNK_ZERO_CODES = ("234", "233", "254", "250", "27", "44", "258", "256", "255", "33", "49", "31")


def normalise_phone(raw: str | None, default_code: str | None = None) -> str | None:
    """'plus two three four, eight oh three...' / '+234 803 123 4567' / '00234...' -> '+2348031234567'.

    A local number ('0814 346 3800') needs default_code: the calling code of where the caller is (from
    their city or time zone). Without it, the caller is asked for the country code. None if unclear."""
    if not raw:
        return None
    words = re.findall(r"\+|[a-z]+|\d", raw.lower())
    text = "".join("+" if w in ("+", "plus") else _DIGIT_WORDS.get(w, w) for w in words
                   if w in ("+", "plus") or w.isdigit() or w in _DIGIT_WORDS)
    if text.startswith("00"):
        text = "+" + text[2:]
    if not text.startswith("+") and default_code:
        text = f"+{default_code}{text[1:] if text.startswith('0') and default_code in TRUNK_ZERO_CODES else text}"
    if not text.startswith("+") or "+" in text[1:]:
        return None
    for code in TRUNK_ZERO_CODES:  # "+234 0814..." (code added to a local number): drop the 0
        if text.startswith(f"+{code}0"):
            text = f"+{code}{text[len(code) + 2:]}"
            break
    digits = text[1:]
    return text if 8 <= len(digits) <= 15 and not digits.startswith("0") else None


def spoken_phone(phone: str) -> str:
    """How the caller would say it: '+2348143463800' -> '0814 346 3800'; unknown codes keep the '+'."""
    code = next((c for c in TRUNK_ZERO_CODES if phone.startswith(f"+{c}")), None)
    if code:
        national = "0" + phone[len(code) + 1:]
    elif phone.startswith("+1") and len(phone) == 12:
        national = phone[2:]
    else:
        national = phone
    first = 4 if len(national) == 11 else 3  # 0814 346 3800 / 024 412 3456 / 415 555 0123
    head, middle, last = national[:first], national[first:-4], national[-4:]
    return " ".join(g for g in [head] + [middle[i:i + 3] for i in range(0, len(middle), 3)] + [last] if g)


def mask_phone(phone: str | None) -> str:
    """For logs: '+2348031234567' -> '+234*******567'."""
    if not phone or len(phone) < 7:
        return "(none)"
    return phone[:4] + "*" * (len(phone) - 7) + phone[-3:]


def mask_email(email: str | None) -> str:
    """For logs: 'amara@lagosledger.example' -> 'a***@lagosledger.example'."""
    if not email or "@" not in email:
        return "(none)"
    local, domain = email.split("@", 1)
    return f"{local[:1]}***@{domain}"
