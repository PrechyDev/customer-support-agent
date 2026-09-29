from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from customer_support_agent.mcp_server.auth import BearerTokenMiddleware

TOKEN = "t" * 32


def make_client():
    async def ok(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/mcp", ok, methods=["GET", "POST"])])
    return TestClient(BearerTokenMiddleware(app, token=TOKEN))


def test_request_without_token_is_rejected():
    response = make_client().post("/mcp")
    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}


def test_request_with_wrong_token_is_rejected():
    response = make_client().post("/mcp", headers={"Authorization": "Bearer " + "w" * 32})
    assert response.status_code == 401


def test_token_without_bearer_prefix_is_rejected():
    response = make_client().post("/mcp", headers={"Authorization": TOKEN})
    assert response.status_code == 401


def test_request_with_correct_token_passes():
    response = make_client().post("/mcp", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200
    assert response.text == "ok"


def test_rejection_is_logged_without_the_token(caplog):
    make_client().post("/mcp", headers={"Authorization": "Bearer leaked-value-123"})
    assert "Rejected MCP request" in caplog.text
    assert "leaked-value-123" not in caplog.text
