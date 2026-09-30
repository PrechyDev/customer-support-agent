"""Vapi's Custom LLM speaks the OpenAI chat-completions format: read its requests, write its replies."""

import json
import time
from dataclasses import dataclass
from typing import Any


class RequestError(ValueError):
    """The request body isn't something we can answer."""


@dataclass(frozen=True)
class ParsedRequest:
    call_id: str | None
    message: str  # the caller's newest words; earlier turns live in the agent session
    stream: bool
    last_assistant: str | None = None  # the agent's previous reply as Vapi recorded it (cut off if interrupted)


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):  # OpenAI "content parts"
        return " ".join(p.get("text", "").strip() for p in content if isinstance(p, dict) and p.get("type") == "text").strip()
    return ""


def parse_request(body: Any) -> ParsedRequest:
    if not isinstance(body, dict) or not isinstance(body.get("messages"), list):
        raise RequestError("body must be a JSON object with a 'messages' list")
    user_messages = [m for m in body["messages"] if isinstance(m, dict) and m.get("role") == "user"]
    if not user_messages:
        raise RequestError("no user message in the request")
    call = body.get("call")
    call_id = call.get("id") if isinstance(call, dict) else None
    last_user = max(i for i, m in enumerate(body["messages"]) if isinstance(m, dict) and m.get("role") == "user")
    earlier_assistant = [m for m in body["messages"][:last_user] if isinstance(m, dict) and m.get("role") == "assistant"]
    return ParsedRequest(
        call_id=str(call_id) if call_id else None,
        message=_text(user_messages[-1].get("content")),
        stream=bool(body.get("stream", False)),
        last_assistant=_text(earlier_assistant[-1].get("content")) if earlier_assistant else None,
    )


def sse_chunk(text: str | None, *, chunk_id: str, model: str, finish: bool = False) -> str:
    payload = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {"content": text} if text else {}, "finish_reason": "stop" if finish else None}],
    }
    return f"data: {json.dumps(payload)}\n\n"


def sse_done() -> str:
    return "data: [DONE]\n\n"


def completion(text: str, *, chunk_id: str, model: str) -> dict[str, Any]:
    """Non-streaming reply, for requests with stream=false."""
    return {
        "id": chunk_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
    }
