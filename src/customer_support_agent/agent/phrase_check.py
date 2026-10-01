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
                                   r"(?:by|on|before|tomorrow|today|within)\b", re.IGNORECASE), True),
    ("compliance reason", re.compile(r"\bcompliance review\b", re.IGNORECASE), False),
    ("internal notes", re.compile(r"\b(?:support|internal|account)\s+notes?\b", re.IGNORECASE), False),
    ("risk logic", re.compile(r"\brisk (?:score|rules?|logic|flags?)\b", re.IGNORECASE), False),
    ("email read aloud", re.compile(r"\b[\w.+-]+\s*(?:@|\sat\s)\s*[\w-]+\s*(?:\.|\sdot\s)\s*[a-z]{2,}\b",
                                    re.IGNORECASE), False),
)


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
