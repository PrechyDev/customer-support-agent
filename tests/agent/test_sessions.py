import asyncio

from customer_support_agent.agent import fallbacks
from customer_support_agent.agent.session import AgentSession, TextDelta
from customer_support_agent.agent.sessions import SessionManager
from tests.agent.fakes import FakeClient, reply, result


class Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


def ok_script():
    return [*reply("Hello."), result()]


class Factory:
    """Creates sessions around fake clients and remembers them."""

    def __init__(self, scripts=None, fail=False, delay=0.0):
        self.scripts = scripts or {}
        self.fail = fail
        self.delay = delay
        self.created: dict[str, FakeClient] = {}

    async def __call__(self, call_id: str, caller=None) -> AgentSession:
        await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("engine failed to start")
        client = self.created[call_id] = FakeClient(self.scripts.get(call_id, [ok_script()] * 5))
        session = AgentSession(client, call_id, turn_timeout_seconds=5)
        await session.start()
        return session


def manager(factory, **kw):
    return SessionManager(factory, max_sessions=kw.get("max_sessions", 10), idle_seconds=180,
                          clock=kw.get("clock", Clock()))


async def ask(m, call_id, message="hi"):
    events = [e async for e in m.ask(call_id, message)]
    return "".join(e.text for e in events if isinstance(e, TextDelta)), events[-1]


def test_one_session_per_call_reused_across_turns():
    factory = Factory()
    m = manager(factory)

    async def scenario():
        await ask(m, "a", "first")
        await ask(m, "a", "second")
        await ask(m, "b", "other")

    asyncio.run(scenario())
    assert factory.created["a"].queries == ["first", "second"]
    assert factory.created["b"].queries == ["other"]


def test_max_turns_asks_to_rephrase_then_offers_a_specialist():
    hit = [result(subtype="error_max_turns", is_error=True, num_turns=6)]
    m = manager(Factory({"a": [hit, hit]}))

    async def scenario():
        return await ask(m, "a"), await ask(m, "a")

    (first, _), (second, _) = asyncio.run(scenario())
    assert (first, second) == (fallbacks.MAX_TURNS_FIRST, fallbacks.MAX_TURNS_REPEAT)  # no contact: dashboard

    escalated = []

    async def escalate(cid):
        escalated.append(cid)
        return True

    m = SessionManager(Factory({"a": [hit, hit]}), max_sessions=10, idle_seconds=180, clock=Clock(), on_stuck=escalate)
    (_, _), (second, _) = asyncio.run(scenario())
    assert (second, escalated) == (fallbacks.MAX_TURNS_ESCALATED, ["a"])  # said only once the escalation exists


def test_out_of_credit_or_bad_key_ends_the_call_at_once():
    from claude_agent_sdk import AssistantMessage, TextBlock
    billing = [AssistantMessage(content=[TextBlock(text="Credit balance is too low")], model="m", error="billing_error"),
               result(is_error=True)]
    spoken, turn = asyncio.run(ask(manager(Factory({"a": [billing]})), "a"))
    assert (spoken, turn.ends_call, turn.api_error) == (fallbacks.TECHNICAL_GOODBYE, True, "billing_error")


def test_technical_failure_asks_to_repeat_then_ends_the_call():
    err = [result(subtype="error_during_execution", is_error=True)]
    m = manager(Factory({"a": [err, ok_script(), err, err], "empty": [[result()]]}))

    async def scenario():
        return [await ask(m, "a") for _ in range(4)]

    first, recovered, again, second_in_row = asyncio.run(scenario())
    assert (first[0], first[1].ends_call) == (fallbacks.TECHNICAL_PROBLEM, False)  # asks them to speak
    assert recovered[1].outcome == "ok"  # a success resets the count
    assert again[0] == fallbacks.TECHNICAL_PROBLEM
    assert (second_in_row[0], second_in_row[1].ends_call) == (fallbacks.TECHNICAL_GOODBYE, True)
    assert fallbacks.END_CALL_PHRASE in second_in_row[0]
    assert m.active_count == 1  # kept until Vapi says the call ended (the caller may cut in before "Goodbye")
    assert asyncio.run(ask(m, "empty"))[0] == fallbacks.EMPTY_REPLY


def test_empty_message_never_reaches_claude():
    factory = Factory()
    assert asyncio.run(ask(manager(factory), "a", "   "))[0] == fallbacks.EMPTY_REPLY
    assert factory.created == {}


def test_engine_start_failure_ends_the_call_straight_away():
    m = manager(Factory(fail=True))
    spoken, last = asyncio.run(ask(m, "a"))
    assert (spoken, last.outcome, last.ends_call, m.active_count) == (fallbacks.TECHNICAL_GOODBYE, "error", True, 0)


def test_busy_when_too_many_calls():
    m = manager(Factory(), max_sessions=1)

    async def scenario():
        await ask(m, "a")
        return await ask(m, "b")

    spoken, last = asyncio.run(scenario())
    assert (spoken, last.outcome, last.ends_call) == (fallbacks.BUSY_GOODBYE, "busy", True)


def test_only_ending_lines_contain_the_hang_up_word():
    """Vapi hangs up on "goodbye", so any other line containing it would cut the call."""
    ending = {fallbacks.GOODBYE, fallbacks.TECHNICAL_GOODBYE, fallbacks.BUSY_GOODBYE}
    others = {fallbacks.MAX_TURNS_FIRST, fallbacks.MAX_TURNS_REPEAT, fallbacks.TECHNICAL_PROBLEM,
              fallbacks.EMPTY_REPLY, fallbacks.REASSURANCE}
    assert all(line.endswith(fallbacks.END_CALL_PHRASE) for line in ending)  # the last word, so it's spoken
    assert not any("goodbye" in line.lower() for line in others)
    assert "glad i could help" not in fallbacks.GOODBYE.lower()  # the backend has no context of the call


def test_messages_for_the_same_call_wait_their_turn():
    factory = Factory(delay=0.05)
    m = manager(factory)

    async def scenario():
        await asyncio.gather(ask(m, "a", "one"), ask(m, "a", "two"))

    asyncio.run(scenario())
    assert len(factory.created) == 1  # the second message didn't start its own engine
    assert sorted(factory.created["a"].queries) == ["one", "two"]


def test_idle_sessions_are_closed_and_close_all_cleans_up():
    clock, factory, abandoned = Clock(), Factory(), []
    m = SessionManager(factory, max_sessions=10, idle_seconds=180, clock=clock, on_idle_close=abandoned.append)

    async def scenario():
        await ask(m, "a")
        clock.now = 100
        await ask(m, "b")
        clock.now = 200  # a idle 200 s, b idle 100 s
        closed = await m.close_idle()
        await m.close_all()
        return closed

    assert asyncio.run(scenario()) == ["a"]
    assert abandoned == ["a"]  # only the idle one counts as abandoned, not those closed at shutdown
    assert all(c.disconnected for c in factory.created.values())
    assert m.active_count == 0


def test_prewarm_starts_the_engine_before_the_first_words_and_respects_the_cap():
    factory = Factory()
    m = manager(factory, max_sessions=1)

    async def scenario():
        await m.prewarm("a")  # Vapi says the call started
        started_before_speaking = "a" in factory.created
        await ask(m, "a", "hi")  # first words reuse the warm session
        await m.prewarm("a")  # repeated event: no second engine
        await m.prewarm("b")  # over the cap: ignored
        return started_before_speaking

    assert asyncio.run(scenario()) is True
    assert factory.created["a"].queries == ["hi"]
    assert "b" not in factory.created


def test_a_hung_prewarm_never_leaves_the_caller_in_silence():
    m = SessionManager(Factory(delay=5), max_sessions=10, idle_seconds=180, wait_seconds=0.1, clock=Clock())

    async def scenario():
        warming = asyncio.create_task(m.prewarm("a"))  # the engine start hangs
        await asyncio.sleep(0.01)
        said = await ask(m, "a")
        warming.cancel()
        return said

    spoken, last = asyncio.run(scenario())
    assert (spoken, last.outcome) == (fallbacks.TECHNICAL_PROBLEM, "timeout")


def test_end_call_signal_makes_the_backend_say_the_goodbye_and_hang_up():
    m = manager(Factory({"a": [[*reply("<end_call/>", say=False), result()]]}))
    spoken, last = asyncio.run(ask(m, "a", "no, that's all"))
    assert (spoken, last.ends_call) == (fallbacks.GOODBYE, True)
    assert m.active_count == 1  # still there if the caller cuts into the goodbye...
    asyncio.run(m.close("a"))  # ...until Vapi's end-of-call event closes it
    assert m.active_count == 0


def test_a_form_that_arrives_after_the_session_is_built_is_told_to_the_agent_once():
    factory = Factory()
    m = manager(factory)
    form = {"name": "Ada", "email": "ada@example.com"}

    async def scenario():
        await m.prewarm("a")  # Vapi's call-started event: no form yet
        await ask_with(m, "a", "hi", form)  # the first request carries the form
        await ask_with(m, "a", "again", form)

    asyncio.run(scenario())
    first, second = factory.created["a"].queries
    assert first.startswith("[System note: the caller filled in the pre-call form: name, email.")
    assert first.endswith("\nhi") and second == "again"  # told once, then never again


async def ask_with(m, call_id, message, caller):
    return [e async for e in m.ask(call_id, message, caller)]
