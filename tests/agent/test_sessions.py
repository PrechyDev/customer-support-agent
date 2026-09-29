import asyncio

from customer_support_agent.agent import fallbacks
from customer_support_agent.agent.session import AgentSession, TextDelta
from customer_support_agent.agent.sessions import SessionManager
from tests.agent.fakes import FakeClient, assistant, delta, result, text


class Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


def ok_script():
    return [delta("Hello."), assistant(text("Hello.")), result()]


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


def test_failures_and_empty_replies_get_spoken_lines():
    scripts = {"err": [[result(subtype="error_during_execution", is_error=True)]], "empty": [[result()]]}
    m = manager(Factory(scripts))
    assert asyncio.run(ask(m, "err"))[0] == fallbacks.TECHNICAL_PROBLEM
    assert asyncio.run(ask(m, "empty"))[0] == fallbacks.EMPTY_REPLY


def test_empty_message_never_reaches_claude():
    factory = Factory()
    assert asyncio.run(ask(manager(factory), "a", "   "))[0] == fallbacks.EMPTY_REPLY
    assert factory.created == {}


def test_engine_start_failure_is_spoken_and_not_kept():
    m = manager(Factory(fail=True))
    spoken, last = asyncio.run(ask(m, "a"))
    assert (spoken, last.outcome, m.active_count) == (fallbacks.TECHNICAL_PROBLEM, "error", 0)


def test_busy_when_too_many_calls():
    m = manager(Factory(), max_sessions=1)

    async def scenario():
        await ask(m, "a")
        return await ask(m, "b")

    spoken, last = asyncio.run(scenario())
    assert (spoken, last.outcome) == (fallbacks.BUSY, "busy")


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
