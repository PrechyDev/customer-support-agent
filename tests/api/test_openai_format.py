import json

import pytest

from customer_support_agent.api.openai_format import RequestError, parse_request, sse_chunk, sse_done


def test_reads_latest_user_message_and_call_id():
    body = {
        "stream": True,
        "call": {"id": "call-123"},
        "messages": [
            {"role": "system", "content": "ignored"},
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": [{"type": "text", "text": "what fees"}, {"type": "text", "text": "do you charge?"}]},
        ],
    }
    parsed = parse_request(body)
    assert (parsed.call_id, parsed.message, parsed.stream) == ("call-123", "what fees do you charge?", True)
    assert parsed.last_assistant == "reply"  # the agent's previous reply, as Vapi recorded it


def test_bad_requests_raise_clear_errors():
    for body in ({}, {"messages": "nope"}, {"messages": [{"role": "assistant", "content": "hi"}]}, []):
        with pytest.raises(RequestError):
            parse_request(body)
    assert parse_request({"messages": [{"role": "user", "content": "hi"}]}).call_id is None  # missing id is allowed


def test_sse_chunks_are_openai_format():
    chunk = sse_chunk("Hello", chunk_id="c1", model="relaypay-agent")
    assert chunk.startswith("data: ") and chunk.endswith("\n\n")
    data = json.loads(chunk[len("data: "):])
    assert data["object"] == "chat.completion.chunk"
    assert data["choices"][0]["delta"] == {"content": "Hello"}
    final = json.loads(sse_chunk(None, chunk_id="c1", model="m", finish=True)[len("data: "):])
    assert final["choices"][0]["finish_reason"] == "stop"
    assert sse_done() == "data: [DONE]\n\n"
