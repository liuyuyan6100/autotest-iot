import pytest

from autotest_mcp.transport import BearerAuthMiddleware

from conftest import drive_asgi


class _EchoApp:
    async def __call__(self, scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


@pytest.mark.asyncio
async def test_no_token_disables_auth():
    app = BearerAuthMiddleware(_EchoApp(), token="")
    status, _ = await drive_asgi(app, headers=[])
    assert status == 200


@pytest.mark.asyncio
async def test_missing_token_rejected():
    app = BearerAuthMiddleware(_EchoApp(), token="secret")
    status, body = await drive_asgi(app, headers=[])
    assert status == 401
    assert body["error"] == "unauthorized"


@pytest.mark.asyncio
async def test_wrong_token_rejected():
    app = BearerAuthMiddleware(_EchoApp(), token="secret")
    status, _ = await drive_asgi(app, headers=[("authorization", "Bearer nope")])
    assert status == 401


@pytest.mark.asyncio
async def test_correct_token_forwarded():
    app = BearerAuthMiddleware(_EchoApp(), token="secret")
    status, body = await drive_asgi(app, headers=[("authorization", "Bearer secret")])
    assert status == 200
    assert body == "ok"
