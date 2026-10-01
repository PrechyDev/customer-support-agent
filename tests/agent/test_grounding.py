from customer_support_agent.agent.grounding import NOT_GROUNDED, assess
from customer_support_agent.agent.session import TurnResult

KB = "mcp__relaypay__search_knowledge_base"


def turn(**kw):
    return TurnResult(outcome="ok", text=kw.pop("text", "Some reply."), **kw)


def test_an_answer_is_grounded_only_by_chunks_this_turn_found_or_a_lookup():
    cited_and_found = assess(turn(answer_type="answer", sources=("fees",), kb_chunks=("fees", "x"), tools_used=(KB,)), "")
    invented = assess(turn(answer_type="answer", sources=("fees", "made-up"), kb_chunks=("fees",)), "")
    from_lookup = assess(turn(answer_type="answer", tools_used=("mcp__relaypay__lookup_transaction",)), "")
    from_nowhere = assess(turn(), "")  # unlabelled, no source, no tool
    assert (cited_and_found.grounded, invented.grounded, from_lookup.grounded, from_nowhere.grounded) == (
        True, False, True, False)
    assert NOT_GROUNDED in invented.note and "made-up" in invented.note
    assert from_nowhere.note.startswith("No answer type given") and NOT_GROUNDED in from_nowhere.note


def test_other_paths_and_backend_lines_are_labelled_without_a_grounding_verdict():
    escalated = assess(turn(answer_type="escalate", tools_used=("mcp__relaypay__create_escalation",)), "")
    only_promised = assess(turn(answer_type="escalate"), "")
    fixed_line = assess(TurnResult(outcome="timeout", fallback="Sorry, could you say that again?"), "Sorry...")
    cut_off = assess(None, "Fees depend")
    assert (escalated.answer_type, escalated.grounded) == ("escalate", None)
    assert "escalation recorded" in escalated.note and "no escalation record" in only_promised.note
    assert (fixed_line.answer_type, cut_off.answer_type) == ("fallback", "answer")
    assert assess(turn(answer_type="decline"), "").answer_type == "decline"
