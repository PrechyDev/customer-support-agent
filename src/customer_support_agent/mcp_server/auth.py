"""Bearer-token check in front of the MCP endpoint (SPECS §8)."""

import hmac
import json
import logging

from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)


class BearerTokenMiddleware:
    """Rejects any HTTP request whose Authorization header isn't exactly 'Bearer <token>'."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self._app = app
        self._expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":  # lifespan events pass straight through
            await self._app(scope, receive, send)
            return

        provided = dict(scope.get("headers") or []).get(b"authorization", b"")
        if hmac.compare_digest(provided, self._expected):  # constant time: no timing leaks
            await self._app(scope, receive, send)
            return

        client = scope.get("client") or ("unknown", 0)
        logger.warning("Rejected MCP request: missing or invalid token (client=%s path=%s)", client[0], scope.get("path"))
        body = json.dumps({"error": "unauthorized"}).encode()
        await send({"type": "http.response.start", "status": 401,
                    "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")]})
        await send({"type": "http.response.body", "body": body})
