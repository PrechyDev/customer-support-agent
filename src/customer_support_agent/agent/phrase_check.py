"""Log-only check of what Bex actually said (SPECS §8.5).

Runs after the reply was sent, so it adds no delay and never changes a reply. It catches the things
the prompt forbids but can't guarantee: promises, internal reasons, notes, contact details read aloud.
A match goes in the turn's confidence note ("PHRASE FLAG: ...") and the log, for review.
"""

import re

# "I can't guarantee" is the right answer, not a promise: skip a match with a negation just before it.
_NEGATED = re.compile(r"\b(?:can't|cannot|can not|won't|don't|do not|not|never|no)\b[\w\s']{0,12}$", re.IGNORECASE)  # close, same clause

_RULES = (
    ("guarantee", re.compile(r"\bguarantee", re.IGNORECASE), True),
    ("promised timing", re.compile(r"\b(?:will|should)\s+(?:arrive|land|reach you|be there|clear)\s+"
                                   r"(?:by|on|before|tomorrow|today|within)\b"
                                   r"|\b(?:shortly|right away|straight away|immediately)\b"
                                   r"|\bwithin\s+(?:\w+\s+)?(?:minutes?|hours?|days?)\b", re.IGNORECASE), True),
    ("compliance reason", re.compile(r"\bcompliance review\b", re.IGNORECASE), False),
    ("internal notes", re.compile(r"\b(?:support|internal|account)\s+notes?\b", re.IGNORECASE), False),
    ("risk logic", re.compile(r"\brisk (?:score|rules?|logic|flags?)\b", re.IGNORECASE), False),
)
# No "email read aloud" rule: tools never give the model a stored email, so the only emails it can say are
# ones the caller just gave, which it must read back.

# What the caller says that should be on record even if the agent forgets to log it (log-only).
_CALLER_RULES = (
    ("injection_attempt", re.compile(r"\b(?:ignore|forget|disregard)\b[\w\s']{0,30}?\b(?:instructions|rules|prompt)\b"
                                     r"|\bsystem prompt\b|\byour (?:instructions|prompt)\b|\bdeveloper mode\b"
                                     r"|\bpretend (?:to be|you are)\b|\byou are now\b", re.IGNORECASE)),
    ("sensitive_request", re.compile(r"\bwhat (?:email|phone|number|address) do you have\b|\banother customer\b"
                                     r"|\bsomeone else'?s (?:account|details|payment)\b|\b(?:support|internal) notes?\b"
                                     r"|\bdetails (?:for|of|about) (?:cus|customer)\b", re.IGNORECASE)),
)


def flag_caller(text: str) -> list[str]:
    """Event types the caller's words suggest (injection_attempt, sensitive_request); empty if none."""
    return [event for event, pattern in _CALLER_RULES if pattern.search(text or "")]


def flag_phrases(text: str) -> list[str]:
    """Names of the rules the spoken text breaks; empty if none."""
    flags = []
    for name, pattern, negatable in _RULES:
        for match in pattern.finditer(text or ""):
            if negatable and _NEGATED.search(text[: match.start()]):
                continue
            flags.append(name)
            break
    return flags
