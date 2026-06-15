"""传输层：把 FastMCP 的 Starlette app 包一层 bearer-token 鉴权，再交给 uvicorn。

tailscale 不进代码——host/端口/mTLS 都是普通参数：
- 家用原型：host 填 tailscale 网卡 IP，靠 tailnet 可达。
- 公司：host 填内网/VPN IP，靠 bearer token + mTLS（对接公司 CA）自包含鉴权。
"""
from __future__ import annotations

import ssl
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import MTlsConfig


async def _send_json(send: Any, status: int, payload: dict[str, Any]) -> None:
    import json

    body = json.dumps(payload).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class BearerAuthMiddleware:
    """纯 ASGI 中间件：校验 Authorization: Bearer <token>。token 为空 = 关闭鉴权（仅 stdio/本机调试用）。"""

    def __init__(self, app: Any, token: str) -> None:
        self.app = app
        self.token = token.strip()

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or not self.token:
            await self.app(scope, receive, send)
            return
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers", [])
        }
        if headers.get("authorization", "") == f"Bearer {self.token}":
            await self.app(scope, receive, send)
            return
        await _send_json(send, 401, {"error": "unauthorized"})


def build_http_app(mcp: FastMCP, token: str) -> Any:
    """FastMCP 的 streamable-http app 外面套 bearer 鉴权。"""
    app = mcp.streamable_http_app()
    return BearerAuthMiddleware(app, token)


def uvicorn_kwargs(host: str, port: int, mtls: MTlsConfig) -> dict[str, Any]:
    kw: dict[str, Any] = {"host": host, "port": port}
    if mtls.enabled:
        kw.update(
            ssl_certfile=mtls.server_cert or None,
            ssl_keyfile=mtls.server_key or None,
            ssl_ca_certs=mtls.client_ca or None,
            ssl_cert_reqs=ssl.CERT_REQUIRED if mtls.client_ca else ssl.CERT_NONE,
        )
    return kw


def run_http(app: Any, host: str, port: int, mtls: MTlsConfig) -> None:
    import uvicorn

    uvicorn.run(app, **uvicorn_kwargs(host, port, mtls))
