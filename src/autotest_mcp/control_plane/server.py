"""控制面 server：FastMCP（唯一入口）+ /gateways HTTP 注册路由 + bearer 鉴权。

- MCP tools：call_hardware / list_gateways / register_gateway / heartbeat（agent 与网关都可经 MCP 调）
- HTTP 路由：/gateways/{id}/register|heartbeat、GET /gateways（供 GatewayRegistrar 的轻量 http 心跳）
两者共享同一个 ControlPlane 实例。家用/公司 host 可配，tailscale 不进代码。
"""
from __future__ import annotations

import ssl
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from ..config import MTlsConfig
from ..transport import BearerAuthMiddleware
from .plane import ControlPlane


def build_control_plane(plane: ControlPlane) -> FastMCP:
    mcp = FastMCP("autotest-control-plane")

    @mcp.tool()
    async def call_hardware(board: str, op: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """把硬件请求路由到拥有该板且在线的网关；离线则入队。"""
        return await plane.call_hardware(board, op, args or {})

    @mcp.tool()
    def list_gateways() -> list[dict[str, Any]]:
        """列出所有网关及在线状态。"""
        return plane.list_gateways()

    @mcp.tool()
    async def register_gateway(
        gw_id: str, url: str, token: str, boards: list[str]
    ) -> dict[str, Any]:
        """网关注册（也可走 HTTP /gateways/{id}/register）。上线即续跑排队作业。"""
        plane.register_gateway(gw_id, url, token, boards)
        await plane.drain_pending(gw_id)
        return {"ok": True, "online": True}

    @mcp.tool()
    async def heartbeat(gw_id: str) -> dict[str, Any]:
        gw = plane.heartbeat(gw_id)
        if gw is None:
            return {"ok": False, "error": "unknown gateway"}
        await plane.drain_pending(gw_id)
        return {"ok": True}

    return mcp


def _http_routes(plane: ControlPlane) -> list[Route]:
    async def register(request):
        gw_id = request.path_params["id"]
        body = await request.json()
        plane.register_gateway(gw_id, body.get("url", ""), body.get("token", ""), body.get("boards", []))
        await plane.drain_pending(gw_id)
        return JSONResponse({"ok": True})

    async def heartbeat(request):
        gw_id = request.path_params["id"]
        gw = plane.heartbeat(gw_id)
        if gw is None:
            return JSONResponse({"ok": False, "error": "unknown gateway"}, status_code=404)
        await plane.drain_pending(gw_id)
        return JSONResponse({"ok": True})

    async def list_gw(_request):
        return JSONResponse(plane.list_gateways())

    return [
        Route("/gateways/{id}/register", register, methods=["POST"]),
        Route("/gateways/{id}/heartbeat", heartbeat, methods=["POST"]),
        Route("/gateways", list_gw, methods=["GET"]),
    ]


def build_app(plane: ControlPlane, token: str) -> Any:
    mcp = build_control_plane(plane)
    mcp_app = mcp.streamable_http_app()  # 内部 /mcp 路由
    # 把 HTTP 注册路由挂到同一个 Starlette app 上
    mcp_app.routes.extend(_http_routes(plane))
    return BearerAuthMiddleware(mcp_app, token)


def run_server(plane: ControlPlane, host: str, port: int, token: str, mtls: MTlsConfig | None = None) -> None:
    import uvicorn

    kw: dict[str, Any] = {"host": host, "port": port}
    if mtls and mtls.enabled:
        kw.update(
            ssl_certfile=mtls.server_cert or None,
            ssl_keyfile=mtls.server_key or None,
            ssl_ca_certs=mtls.client_ca or None,
            ssl_cert_reqs=ssl.CERT_REQUIRED if mtls.client_ca else ssl.CERT_NONE,
        )
    uvicorn.run(build_app(plane, token), **kw)
