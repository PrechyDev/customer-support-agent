"""The backend's own check of each reply, written to conversation_turns as answer_type + confidence_note.

The model labels its reply <say type="answer|clarify|escalate|decline" sources="chunk-ids">. The note is
written here, not by the model: an "answer" counts as grounded only if every chunk it cites was really
returned by this turn's knowledge base search, or it came from an account lookup this turn. Anything
else is flagged NOT GROUNDED so it stands out when reviewing calls.
"""

from dataclasses import dataclass

from customer_support_agent.agent.session import TurnResult

# Tools whose result the caller can be told directly (a status, a ticket or escalation confirmation).
LOOKUP_TOOLS = ("lookup_customer", "lookup_transaction", "lookup_payout", "create_support_ticket", "create_escalation")
NOT_GROUNDED = "NOT GROUNDED"


@dataclass(frozen=True)
class Assessment:
    answer_type: str  # one of the conversation_turns.answer_type values
    note: str
    grounded: bool | None  # None when the reply makes no factual claim to check


def _short(tool: str) -> str:
    return tool.rsplit("__", 1)[-1]


def assess(result: TurnResult | None, sent_text: str) -> Assessment:
    if result is None:  # the request was cancelled before the turn finished (barge-in)
        return Assessment("answer" if sent_text else "fallback",
                          "Cut off: the caller interrupted before the reply finished.", None)
    tools = [_short(t) for t in result.tools_used]
    if not result.text:
        return Assessment("fallback", f"Fixed backend line ({result.outcome}).", None)

    answer_type = result.answer_type or "answer"
    unlabelled = "" if result.answer_type else "No answer type given; checked as an answer. "
    extra = f" Followed by a fixed line ({result.outcome})." if result.fallback else ""

    if answer_type == "answer":
        cited, found = set(result.sources), set(result.kb_chunks)
        if cited and cited <= found:
            return Assessment("answer", f"{unlabelled}Grounded in: {', '.join(result.sources)}.{extra}", True)
        if cited:
            missing = ", ".join(s for s in result.sources if s not in found)
            return Assessment("answer", f"{unlabelled}{NOT_GROUNDED}: cited {missing}, not returned by this "
                                        f"turn's search.{extra}", False)
        lookups = [t for t in tools if t in LOOKUP_TOOLS]
        if lookups:
            return Assessment("answer", f"{unlabelled}From tool result: {', '.join(lookups)}.{extra}", True)
        earlier = [t for t in dict.fromkeys(_short(t) for t in result.call_tools) if t in LOOKUP_TOOLS]
        if earlier:  # repeating a status or confirmation from earlier in the call
            return Assessment("answer", f"{unlabelled}From an earlier tool result in this call: {', '.join(earlier)}.{extra}",
                              True)
        return Assessment("answer", f"{unlabelled}{NOT_GROUNDED}: no knowledge base source or lookup this turn.{extra}",
                          False)
    if answer_type == "escalate":
        done = "escalation recorded" if "create_escalation" in tools else "no escalation record created this turn"
        return Assessment("escalate", f"Escalation path; {done}.{extra}", None)
    if answer_type == "decline":
        searched = "after a knowledge base search" if "search_knowledge_base" in tools else "without a search"
        return Assessment("decline", f"Declined {searched}.{extra}", None)
    return Assessment("clarify", f"Question or conversational reply; no facts stated.{extra}", None)
