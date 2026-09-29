from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from customer_support_agent.mcp_server.auth import BearerTokenMiddleware

TOKEN = "t" * 32


def client():
    async def ok(request):
        return PlainTextResponse("ok")

    return TestClient(BearerTokenMiddleware(Starlette(routes=[Route("/mcp", ok, methods=["POST"])]), token=TOKEN))


def test_correct_token_passes():
    assert client().post("/mcp", headers={"Authorization": f"Bearer {TOKEN}"}).text == "ok"


def test_missing_wrong_or_unprefixed_token_is_rejected_and_not_logged(caplog):
    for headers in ({}, {"Authorization": "Bearer leaked-value-123"}, {"Authorization": TOKEN}):
        response = client().post("/mcp", headers=headers)
        assert response.status_code == 401
        assert response.json() == {"error": "unauthorized"}
    assert "Rejected MCP request" in caplog.text
    assert "leaked-value-123" not in caplog.text
