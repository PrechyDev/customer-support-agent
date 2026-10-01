"""What a caller may hear about a transaction or payout, and what happens next (SPECS §5).

Decided from the status first, then the date. The model gets only the result, never the raw record.
"""

from dataclasses import dataclass
from datetime import date
from typing import Literal

NextStep = Literal["none", "ticket", "escalate"]

# {thing} is "that payment" (a transaction) or "that payout": never a bare "it", which is unclear when the caller
# has mentioned both.
_LINES = {
    "processing": "{Thing} is still being processed.",
    "scheduled": "{Thing} is scheduled.",
    "delayed": "I'm sorry, {thing} is taking a bit longer than usual.",
    "completed": "Good news, {thing} shows as completed.",
    "failed": "I'm sorry, it looks like {thing} didn't go through.",
    "under review": "{Thing} is currently being reviewed.",
    "unknown": "I can't confirm the status of {thing} right now.",
}
_THING = {"transaction": "that payment", "payout": "that payout"}


@dataclass(frozen=True)
class CallerStatus:
    status: str  # what the caller may hear
    line: str  # a neutral sentence Bex can say as is
    next_step: NextStep


def _line(word: str, kind: str) -> str:
    thing = _THING[kind]
    return _LINES[word].format(thing=thing, Thing=thing[0].upper() + thing[1:])


def caller_status(kind: Literal["transaction", "payout"], stored: str, due: date | None, today: date) -> CallerStatus:
    word, next_step = _decide(kind, stored, due, today)
    return CallerStatus(status=word, line=_line(word, kind), next_step=next_step)


def _decide(kind: str, stored: str, due: date | None, today: date) -> tuple[str, NextStep]:
    """`due` is estimated_arrival (transactions) or scheduled_for (payouts); it's ignored for final states."""
    if stored in ("processing", "scheduled"):
        if due is not None and due < today:  # the date has passed: it's late, whatever the record says
            return ("delayed", "escalate")
        return (stored, "none")
    if stored == "delayed":
        return ("delayed", "escalate")
    if stored == "completed":
        return ("completed", "none")
    if stored == "failed":  # a failed payout involves beneficiary details: always a human
        return ("failed", "escalate" if kind == "payout" else "ticket")
    if stored == "review required":
        return ("under review", "escalate")
    return ("unknown", "escalate")
