"""What a caller may hear about a transaction or payout, and what happens next (SPECS §5).

Decided from the status first, then the date. The model gets only the result, never the raw record.
"""

from dataclasses import dataclass
from datetime import date
from typing import Literal

NextStep = Literal["none", "ticket", "escalate"]

_LINES = {
    "processing": "It's currently processing.",
    "scheduled": "It's scheduled.",
    "delayed": "It's taking longer than usual.",
    "completed": "It shows as completed.",
    "failed": "It didn't go through.",
    "under review": "It's under review.",
    "unknown": "I can't confirm its status right now.",
}


@dataclass(frozen=True)
class CallerStatus:
    status: str  # what the caller may hear
    line: str  # a neutral sentence Bex can say as is
    next_step: NextStep


def _status(word: str, next_step: NextStep) -> CallerStatus:
    return CallerStatus(status=word, line=_LINES[word], next_step=next_step)


def caller_status(kind: Literal["transaction", "payout"], stored: str, due: date | None, today: date) -> CallerStatus:
    """`due` is estimated_arrival (transactions) or scheduled_for (payouts); it's ignored for final states."""
    if stored in ("processing", "scheduled"):
        if due is not None and due < today:  # the date has passed: it's late, whatever the record says
            return _status("delayed", "escalate")
        return _status(stored, "none")
    if stored == "delayed":
        return _status("delayed", "escalate")
    if stored == "completed":
        return _status("completed", "none")
    if stored == "failed":  # a failed payout involves beneficiary details: always a human
        return _status("failed", "escalate" if kind == "payout" else "ticket")
    if stored == "review required":
        return _status("under review", "escalate")
    return _status("unknown", "escalate")
