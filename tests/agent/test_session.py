import asyncio

from customer_support_agent.agent import session as session_module
from customer_support_agent.agent.session import AgentSession, TextDelta
from tests.agent.fakes import KB_TOOL, FakeClient, assistant_only, reply, result, tool_result


def collect(session, message="fees?"):
    async def run():
        return [e async for e in session.ask(message)]

    return asyncio.run(run())


def spoken(events) -> str:
    return "".join(e.text for e in events if isinstance(e, TextDelta))


def test_narration_before_a_tool_is_dropped_and_the_answer_sent_whole():
    client = FakeClient([[*reply("Let me search for that.", tool=KB_TOOL),
                          *reply("Fees depend on the corridor."), result(num_turns=2, cost=0.0031)]])
    events = collect(AgentSession(client, "call-1", turn_timeout_seconds=5))
    assert [e.text for e in events if isinstance(e, TextDelta)] == ["Fees depend on the corridor."]  # one piece
    turn = events[-1]
    assert (turn.outcome, turn.text, turn.tools_used, turn.num_turns, turn.cost_usd) == (
        "ok", "Fees depend on the corridor.", (KB_TOOL,), 2, 0.0031)


def test_after_a_tool_the_answer_streams_sentence_by_sentence():
    answer = "Fees depend on the corridor. You'll see the exact fee before you confirm."
    client = FakeClient([[*reply("Let me search.", tool=KB_TOOL), *reply(answer, pieces=8), result()]])
    events = collect(AgentSession(client, "call-1", turn_timeout_seconds=5))
    texts = [e.text for e in events if isinstance(e, TextDelta)]
    assert texts == ["Fees depend on the corridor.", " You'll see the exact fee before you confirm."]  # 2 sentences


def test_say_labels_are_read_but_never_spoken_and_found_chunks_are_tracked():
    found = '{"found": true, "results": [{"chunk_id": "fees", "title": "Fees"}, {"chunk_id": "timelines"}]}'
    labelled = '<say type="answer" sources="fees, invented">Fees depend on the corridor. That is all.</say>'
    client = FakeClient([[*reply("Let me search.", tool=KB_TOOL), tool_result(found),
                          *reply(labelled, pieces=12, say=False), result()]])
    events = collect(AgentSession(client, "call-1", turn_timeout_seconds=5))
    turn = events[-1]
    assert spoken(events).startswith("Fees depend on the corridor. That is all.")  # the tag's attributes stay silent
    assert "sources" not in spoken(events) and "type=" not in spoken(events)
    assert (turn.answer_type, turn.sources, turn.kb_chunks) == ("answer", ("fees", "invented"), ("fees", "timelines"))


def test_reasoning_outside_say_tags_is_never_spoken():
    """The exact leak from a real Haiku call: reasoning written as the answer, then the real question."""
    leak = ("The customer has said they don't need a specialist. I should ask if there's anything else. "
            "<say>Sounds good. Anything else I can help with?</say>")
    client = FakeClient([[*reply(leak, say=False, pieces=9), result()]])
    assert spoken(collect(AgentSession(client, "call-1", turn_timeout_seconds=5))) == "Sounds good. Anything else I can help with?"


def test_a_closing_question_after_the_tags_is_kept_but_statements_are_not():
    raw = "<say>That payout is being reviewed.</say> Is there anything else I can help you with?"
    client = FakeClient([[*reply(raw, say=False), result()]])
    assert spoken(collect(AgentSession(client, "c", turn_timeout_seconds=5))) == (
        "That payout is being reviewed. Is there anything else I can help you with?")
    client = FakeClient([[*reply("<say>Done.</say> I should now ask if they need more.", say=False), result()]])
    assert spoken(collect(AgentSession(client, "c", turn_timeout_seconds=5))) == "Done."


def test_an_untagged_short_question_to_the_caller_is_still_spoken():
    """An eval run: "...could you give me the transaction reference for it?" written untagged, twice."""
    ask = "I can help with that. Could you give me the transaction reference for it?"
    client = FakeClient([[*reply(ask, say=False), result()]])
    assert spoken(collect(AgentSession(client, "c", turn_timeout_seconds=5))) == ask
    thinking = "The customer wants a refund. I should ask whether they have the reference?"
    client = FakeClient([[*reply(thinking, say=False), result()]])
    assert spoken(collect(AgentSession(client, "c", turn_timeout_seconds=5))) == ""  # reasoning stays silent


def test_a_reply_without_say_tags_speaks_nothing():
    client = FakeClient([[*reply("I forgot the tags.", say=False), result()]])
    turn = collect(AgentSession(client, "call-1", turn_timeout_seconds=5))[-1]
    assert turn.text == ""  # the manager then asks the caller to repeat


def test_the_model_can_never_say_a_hang_up_phrase():
    """Regression: Haiku greeted a caller with a hang-up phrase and Vapi hung up mid-call."""
    greeting = "Hi there. No need to say Goodbye yet. How can I help with your payout?"
    client = FakeClient([[*reply(greeting), result()]])
    said = spoken(collect(AgentSession(client, "call-1", turn_timeout_seconds=5)))
    assert said == "Hi there. No need to say bye for now yet. How can I help with your payout?"


def test_end_call_signal_is_passed_on():
    client = FakeClient([[*reply("<end_call/>", say=False), result()]])
    turn = collect(AgentSession(client, "call-1", turn_timeout_seconds=5))[-1]
    assert (turn.end_requested, turn.text) == (True, "")


def test_a_call_ending_on_thanks_gets_one_goodbye_only():
    """"No, thank you" in a voice test: the model's "You're welcome. Goodbye!" plus the closing line was two goodbyes."""
    client = FakeClient([[*reply("<say>You're welcome. Goodbye!</say><end_call/>", say=False), result()]])
    turn = collect(AgentSession(client, "call-1", turn_timeout_seconds=5))[-1]
    assert (turn.end_requested, turn.text) == (True, "")  # the backend's closing line says it once
    real = FakeClient([[*reply("<say>Your ticket is T-1050. Goodbye!</say><end_call/>", say=False), result()]])
    assert collect(AgentSession(real, "call-1", turn_timeout_seconds=5))[-1].text == "Your ticket is T-1050. Bye for now!"


def test_an_answer_that_ends_on_a_statement_gets_a_closing_question():
    """Production call: the fee answer just stopped, with no "anything else?"."""
    fee = '<say type="answer" sources="fees">Fees depend on the corridor. You see the fee before you confirm.</say>'
    session = AgentSession(FakeClient([[*reply(fee, say=False), result()], [*reply(fee, say=False), result()]]),
                           "c", turn_timeout_seconds=5)
    first = collect(session)
    assert spoken(first) == f"Fees depend on the corridor. You see the fee before you confirm. {session_module.CLOSING_QUESTIONS[0]}"
    assert first[-1].text.endswith(session_module.CLOSING_QUESTIONS[0])  # on record as said
    assert spoken(collect(session)).endswith(session_module.CLOSING_QUESTIONS[1])  # rotates
    for raw in ('<say type="answer">Your plan is Growth. Anything else?</say>',  # already asks
                '<say type="clarify">Take your time.</say>',  # not an answer
                '<say type="answer">You are welcome.</say><end_call/>'):  # call ending
        said = spoken(collect(AgentSession(FakeClient([[*reply(raw, say=False), result()]]), "c", 5)))
        assert not any(q in said for q in session_module.CLOSING_QUESTIONS)


def test_no_second_question_when_the_reply_already_asks_one():
    raw = "<say>Do you have the reference for me?</say> What's the transaction reference?"
    client = FakeClient([[*reply(raw, say=False), result()]])
    assert spoken(collect(AgentSession(client, "c", turn_timeout_seconds=5))) == "Do you have the reference for me?"


def test_without_stream_events_full_messages_are_used_the_same_way():
    client = FakeClient([[assistant_only("Let me check.", tool=KB_TOOL), assistant_only("Hello, how can I help?"), result()]])
    assert spoken(collect(AgentSession(client, "call-1", turn_timeout_seconds=5))) == "Hello, how can I help?"


def test_sdk_results_map_to_outcomes():
    cases = {"max_turns": [result(subtype="error_max_turns", is_error=True, num_turns=6)],
             "error": [result(subtype="error_during_execution", is_error=True)]}
    for expected, script in cases.items():
        assert collect(AgentSession(FakeClient([script]), "c", turn_timeout_seconds=5))[-1].outcome == expected
    assert collect(AgentSession(FakeClient([reply("Hi")]), "c", turn_timeout_seconds=5))[-1].outcome == "error"  # no result


def test_client_exception_becomes_an_error_result():
    turn = collect(AgentSession(FakeClient(query_error=RuntimeError("connection reset")), "c", turn_timeout_seconds=5))[-1]
    assert turn.outcome == "error" and "connection reset" in turn.error


def test_abandoned_turn_is_drained_so_the_next_turn_hears_its_own_answer():
    """Regression: a cancelled reply's leftovers were read by the next turn as its answer (found in real calls)."""
    client = FakeClient([[*reply("Could you tell me more about what you'd like to know?", pieces=6), result()],
                         [*reply("Exchange rates aren't fixed."), result()]], slow_seconds=0.01)
    session = AgentSession(client, "call-1", turn_timeout_seconds=5)

    async def scenario():
        first = session.ask("okay")
        await anext(first)  # reading has started...
        await first.aclose()  # ...then Vapi cancels the request (barge-in / revised transcript)
        assert await session.ready()  # the next turn waits for the drain
        return [e async for e in session.ask("okay, is there anything I need to know?")]

    events = asyncio.run(scenario())
    assert client.interrupted is True
    assert spoken(events) == "Exchange rates aren't fixed."  # its own answer, not the old leftovers


def test_turn_that_cannot_be_drained_marks_the_session_for_replacement(monkeypatch):
    monkeypatch.setattr(session_module, "DRAIN_TIMEOUT_SECONDS", 0.05)
    client = FakeClient([[]], hang=True)
    session = AgentSession(client, "call-1", turn_timeout_seconds=0.1)

    async def scenario():
        turn = [e async for e in session.ask("fees?")][-1]
        return turn, await session.ready()

    turn, usable = asyncio.run(scenario())
    assert turn.outcome == "timeout" and client.interrupted is True
    assert usable is False


def test_start_connects_and_close_never_raises():
    class BadDisconnect(FakeClient):
        async def disconnect(self):
            raise RuntimeError("already gone")

    client = BadDisconnect()
    session = AgentSession(client, "call-1", turn_timeout_seconds=5)
    asyncio.run(session.start())
    asyncio.run(session.close())
    assert client.connected
