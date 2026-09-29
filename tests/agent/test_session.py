import asyncio

from customer_support_agent.agent.session import AgentSession, TextDelta
from tests.agent.fakes import FakeClient, assistant, delta, result, text, tool_use

KB_TOOL = "mcp__relaypay__search_knowledge_base"


def turn(client, timeout=5):
    async def collect():
        return [e async for e in AgentSession(client, "call-1", turn_timeout_seconds=timeout).ask("fees?")]

    events = asyncio.run(collect())
    return "".join(e.text for e in events if isinstance(e, TextDelta)), events[-1]


def test_streams_the_reply_and_reports_the_turn():
    client = FakeClient([[
        delta("Let me check "), delta("that."), assistant(text("Let me check that."), tool_use(KB_TOOL)),
        delta("Fees depend on the corridor."), assistant(text("Fees depend on the corridor.")),
        result(num_turns=2, cost=0.0031),
    ]])
    spoken, result_ = turn(client)
    assert spoken == "Let me check that. Fees depend on the corridor."  # space between messages
    assert (result_.outcome, result_.tools_used, result_.num_turns, result_.cost_usd) == ("ok", (KB_TOOL,), 2, 0.0031)


def test_full_text_is_spoken_when_no_stream_pieces_arrive():
    spoken, _ = turn(FakeClient([[assistant(text("Hello, how can I help?")), result()]]))
    assert spoken == "Hello, how can I help?"


def test_sdk_results_map_to_outcomes():
    cases = {
        "max_turns": [result(subtype="error_max_turns", is_error=True, num_turns=6)],
        "error": [result(subtype="error_during_execution", is_error=True)],
    }
    for expected, script in cases.items():
        assert turn(FakeClient([script]))[1].outcome == expected
    assert turn(FakeClient([[assistant(text("Hi"))]]))[1].outcome == "error"  # no result message


def test_client_exception_becomes_an_error_result():
    _, result_ = turn(FakeClient(query_error=RuntimeError("connection reset")))
    assert result_.outcome == "error" and "connection reset" in result_.error


def test_slow_turn_times_out_and_interrupts_the_engine():
    client = FakeClient([[]], hang=True)
    assert turn(client, timeout=0.1)[1].outcome == "timeout"
    assert client.interrupted is True


def test_start_connects_and_close_never_raises():
    class BadDisconnect(FakeClient):
        async def disconnect(self):
            raise RuntimeError("already gone")

    client = BadDisconnect()
    session = AgentSession(client, "call-1", turn_timeout_seconds=5)
    asyncio.run(session.start())
    asyncio.run(session.close())
    assert client.connected
