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

    async def __call__(self, call_id: str) -> AgentSession:
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
    assert (first, second) == (fallbacks.MAX_TURNS_FIRST, fallbacks.MAX_TURNS_REPEAT)


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
    assert m.active_count == 0  # engine closed with the call
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


def test_only_ending_lines_contain_an_end_call_phrase():
    """Vapi hangs up on these phrases, so any other line containing one would cut the call."""
    ending = {fallbacks.TECHNICAL_GOODBYE, fallbacks.BUSY_GOODBYE}
    others = {fallbacks.MAX_TURNS_FIRST, fallbacks.MAX_TURNS_REPEAT, fallbacks.TECHNICAL_PROBLEM,
              fallbacks.EMPTY_REPLY, fallbacks.REASSURANCE}
    assert all(fallbacks.END_CALL_PHRASE in line for line in ending)
    for phrase in (fallbacks.END_CALL_PHRASE, "thanks for calling relaypay"):
        assert not any(phrase.lower() in line.lower() for line in others)
    # Vapi hangs up the moment the phrase is spoken, so it must be the last words of the goodbye.
    assert fallbacks.GOODBYE.lower().rstrip(".").endswith("thanks for calling relaypay")


def test_messages_for_the_same_call_wait_their_turn():
    factory = Factory(delay=0.05)
    m = manager(factory)

    async def scenario():
        await asyncio.gather(ask(m, "a", "one"), ask(m, "a", "two"))

    asyncio.run(scenario())
    assert len(factory.created) == 1  # the second message didn't start its own engine
    assert sorted(factory.created["a"].queries) == ["one", "two"]


def test_idle_sessions_are_closed_and_close_all_cleans_up():
    clock, factory = Clock(), Factory()
    m = manager(factory, clock=clock)

    async def scenario():
        await ask(m, "a")
        clock.now = 100
        await ask(m, "b")
        clock.now = 200  # a idle 200 s, b idle 100 s
        closed = await m.close_idle()
        await m.close_all()
        return closed

    assert asyncio.run(scenario()) == ["a"]
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
