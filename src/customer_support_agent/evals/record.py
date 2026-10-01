"""One call's records, read back from the database for scoring, and the score itself."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CallRecord:
    exists: bool
    ended: bool = False
    verified_customer_id: str | None = None
    turns: tuple[dict, ...] = ()
    tools: tuple[str, ...] = ()
    searches: int = 0
    tickets: tuple[dict, ...] = ()
    escalations: tuple[dict, ...] = ()
    events: tuple[str, ...] = ()

    @property
    def spoken(self) -> str:
        return "\n".join(t["assistant_response"] or "" for t in self.turns)

    @property
    def notes(self) -> tuple[str, ...]:
        return tuple(t["confidence_note"] or "" for t in self.turns)


@dataclass(frozen=True)
class Score:
    passed: bool
    actual: str
    failed: tuple[str, ...] = field(default_factory=tuple)


def load_record(repo: Any, cid: str) -> CallRecord:
    conv = repo._run("select verified_customer_id, ended_at from conversations where conversation_id = %s", (cid,), "one")
    if conv is None:
        return CallRecord(exists=False)
    rows = lambda sql: tuple(repo._run(sql, (cid,), "all"))  # noqa: E731
    return CallRecord(
        exists=True,
        ended=conv["ended_at"] is not None,
        verified_customer_id=conv["verified_customer_id"],
        turns=rows("select user_transcript, assistant_response, answer_type, confidence_note from conversation_turns "
                   "where conversation_id = %s order by created_at"),
        tools=tuple(r["tool_name"] for r in rows("select tool_name from tool_calls where conversation_id = %s "
                                                  "and status = 'ok' order by created_at")),  # a refused call did nothing
        searches=len(rows("select 1 from retrieval_logs where conversation_id = %s")),
        tickets=rows("select ticket_id, category, priority, summary from support_tickets where conversation_id = %s"),
        escalations=rows("select e.escalation_id, e.ticket_id, e.reason, e.verified, t.summary as ticket_summary "
                         "from escalations e left join support_tickets t on t.ticket_id = e.ticket_id "
                         "where e.conversation_id = %s"),
        events=tuple(r["event_type"] for r in rows("select event_type from conversation_events "
                                                    "where conversation_id = %s")),
    )


def score(checks, record: CallRecord) -> Score:
    """Pass only if every check holds. `actual` says what the records show, in a line."""
    if not record.exists:
        return Score(False, "no records for this call", ("call recorded",))
    failed = tuple(c.label for c in checks if not c.test(record))
    cases = [e["escalation_id"] for e in record.escalations] + [t["ticket_id"] for t in record.tickets]
    last = record.turns[-1]["assistant_response"] if record.turns else ""
    actual = (f"tools: {', '.join(record.tools) or 'none'}; searches: {record.searches}; "
              f"cases: {', '.join(cases) or 'none'}; events: {', '.join(sorted(set(record.events))) or 'none'}; "
              f"last reply: {(last or '')[:160]}")
    return Score(not failed, actual, failed)
