import asyncio

from customer_support_agent.agent.promise_guard import UNTAGGED_REASON, make_stop_hook, promises_follow_up
from tests.mcp_server.fake_repo import FakeRepository


def run(hook, message, active=False):
    data = {"hook_event_name": "Stop", "stop_hook_active": active, "last_assistant_message": message}
    return asyncio.run(hook(data, None, None))


def test_recognises_a_promised_follow_up_but_not_an_offer():
    assert promises_follow_up("Lovely, a specialist will email you.")
    assert promises_follow_up("Our team will be in touch.")
    assert not promises_follow_up("Would you like a specialist to call you back, or reach you by email?")
    assert not promises_follow_up("Fees depend on the corridor.")


def test_a_promise_without_an_escalation_makes_the_agent_create_it_once_then_is_logged():
    repo = FakeRepository()
    repo.ensure_conversation("c1", caller={"name": "Ada", "email": "ada@example.com"})
    hook = make_stop_hook(repo, "c1", lambda: "")

    blocked = run(hook, "<say>Lovely, a specialist will email you.</say>")
    assert blocked["decision"] == "block" and "create_escalation" in blocked["reason"]
    assert run(hook, "Lovely, a specialist will email you.", active=True) == {}  # second time: never loops
    assert [e[1] for e in repo.events] == ["other"]  # staff can see the promise had no record

    repo.create_escalation({"conversation_id": "c1", "category": "payment", "ticket_id": None}, "x", {})
    assert run(hook, "<say>Lovely, a specialist will email you.</say>") == {}  # kept: nothing to do
    assert run(make_stop_hook(repo, "c2", lambda: "a specialist will call you"), "") != {}  # spoken text counts too


def test_a_reply_without_say_tags_is_asked_for_again_once():
    hook = make_stop_hook(None, "c1", lambda: "")
    assert run(hook, "I need your transaction reference. Could you give me that?") == {
        "decision": "block", "reason": UNTAGGED_REASON}
    assert run(hook, "Still no tags.", active=True) == {}  # never loops
    assert run(hook, "<say>Fine.</say>") == {} and run(hook, "<end_call/>") == {}
    assert run(make_stop_hook(None, "c1", lambda: "Already said."), "trailing note") == {}
